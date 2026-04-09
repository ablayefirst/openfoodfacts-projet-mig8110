#!/usr/bin/env python3
import argparse
import gzip
import io
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg2
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from airflow.exceptions import AirflowSkipException
except ImportError:
    class AirflowSkipException(RuntimeError):
        pass


DEFAULT_FULL_JSONL_URL = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"
DEFAULT_DELTA_INDEX_URL = "https://static.openfoodfacts.org/data/delta/index.txt"
DEFAULT_DELTA_BASE_URL = "https://static.openfoodfacts.org/data/delta"
DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
DOWNLOAD_MAX_ATTEMPTS = 8


def env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return int(raw_value)


def env_str(name: str, default: str) -> str:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return raw_value.strip()


def not_empty(obj: dict[str, Any], key: str) -> bool:
    value = obj.get(key)
    return value is not None and str(value).strip() != ""


def has_country(product: dict[str, Any], country: str) -> bool:
    country = country.lower()
    countries = str(product.get("countries") or "").lower()
    tags = [str(tag).lower() for tag in (product.get("countries_tags") or [])]
    return country in countries or f"en:{country}" in tags


def value_present(value: Any) -> bool:
    if value is None:
        return False
    txt = str(value).strip()
    if not txt:
        return False
    return txt.lower() not in {"nan", "none", "null"}


def nutrient_present(product: dict[str, Any], *keys: str) -> bool:
    nutriments = product.get("nutriments") or {}
    if not isinstance(nutriments, dict):
        nutriments = {}

    for key in keys:
        if value_present(product.get(key)) or value_present(nutriments.get(key)):
            return True
    return False


def count_core_nutrients(product: dict[str, Any]) -> int:
    count = 0
    if nutrient_present(product, "energy-kcal_100g", "energy_kcal_100g", "energy-kj_100g", "energy_100g"):
        count += 1
    if nutrient_present(product, "sugars_100g"):
        count += 1
    if nutrient_present(product, "fat_100g"):
        count += 1
    if nutrient_present(product, "salt_100g", "sodium_100g"):
        count += 1
    return count


def has_category(product: dict[str, Any]) -> bool:
    return bool(product.get("categories_tags") or product.get("categories"))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract Open Food Facts official exports (full dump or 14-day deltas)."
    )
    parser.add_argument(
        "--source-mode",
        choices=["official", "local"],
        default=env_str("OPENFOOD_SOURCE_MODE", "official"),
        help="Use official OpenFoodFacts exports or a local JSONL source file.",
    )
    parser.add_argument(
        "--local-file",
        default=env_str("OPENFOOD_LOCAL_FILE", ""),
        help="Path to a local JSONL file when --source-mode=local.",
    )
    parser.add_argument("--mode", choices=["auto", "full", "delta"], default="auto")
    parser.add_argument("--output-dir", default="/opt/airflow/data")
    parser.add_argument("--country", default=os.getenv("OPENFOOD_COUNTRY", "canada"))
    parser.add_argument(
        "--min-core-nutrients",
        type=int,
        default=env_int("OPENFOOD_MIN_CORE_NUTRIENTS", 2),
        help="Minimum number of core nutrients present among energy/sugars/fat/salt (0 disables filter).",
    )
    parser.add_argument(
        "--full-refresh-interval-days",
        type=int,
        default=env_int("OPENFOOD_FULL_REFRESH_INTERVAL_DAYS", 56),
    )
    parser.add_argument(
        "--delta-retention-days",
        type=int,
        default=env_int("OPENFOOD_DELTA_RETENTION_DAYS", 14),
    )
    parser.add_argument(
        "--full-jsonl-url",
        default=os.getenv("OPENFOOD_FULL_JSONL_URL", DEFAULT_FULL_JSONL_URL),
    )
    parser.add_argument(
        "--delta-index-url",
        default=os.getenv("OPENFOOD_DELTA_INDEX_URL", DEFAULT_DELTA_INDEX_URL),
    )
    parser.add_argument(
        "--delta-base-url",
        default=os.getenv("OPENFOOD_DELTA_BASE_URL", DEFAULT_DELTA_BASE_URL),
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=env_int("OPENFOOD_MAX_ROWS", 500),
        help="Maximum number of filtered rows to keep (0 disables the limit).",
    )
    parser.add_argument(
        "--full-mode",
        choices=["direct", "sample"],
        default=env_str("OPENFOOD_FULL_MODE", "direct"),
        help="For full imports: process the whole dump directly or create a raw sample first.",
    )
    parser.add_argument(
        "--full-sample-size",
        type=int,
        default=env_int("OPENFOOD_FULL_SAMPLE_SIZE", 5000),
        help="Raw sample size used when --full-mode=sample.",
    )
    parser.add_argument(
        "--full-sample-strategy",
        choices=["first", "random"],
        default=env_str("OPENFOOD_FULL_SAMPLE_STRATEGY", "first"),
        help="Sampling strategy used when --full-mode=sample.",
    )
    parser.add_argument(
        "--full-sample-seed",
        type=int,
        default=env_int("OPENFOOD_FULL_SAMPLE_SEED", 42),
        help="Random seed used when --full-sample-strategy=random.",
    )
    parser.add_argument(
        "--delta-max-files",
        type=int,
        default=env_int("OPENFOOD_DELTA_MAX_FILES", 0),
        help="Maximum number of pending delta files to process (0 uses all pending deltas).",
    )
    return parser.parse_args()


def make_session(total_retries: int = 6, backoff: float = 1.0) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": os.getenv(
                "OPENFOOD_HTTP_USER_AGENT",
                (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36 "
                    "openfoodfacts-projet-etl/1.0"
                ),
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        }
    )
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_pg_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "openfood_db"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres123"),
    )


def ensure_import_history_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS etl_import_history (
            import_id SERIAL PRIMARY KEY,
            import_type TEXT NOT NULL,
            bronze_key TEXT,
            silver_key TEXT,
            source_reference TEXT,
            source_start_ts BIGINT,
            source_end_ts BIGINT,
            rows_input INTEGER NOT NULL DEFAULT 0,
            rows_loaded INTEGER NOT NULL DEFAULT 0,
            imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_etl_import_history_imported_at
        ON etl_import_history (imported_at);
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_etl_import_history_type_end_ts
        ON etl_import_history (import_type, source_end_ts);
        """
    )


def get_import_state() -> dict[str, Any]:
    state = {
        "last_success_at": None,
        "last_full_at": None,
        "last_delta_end_ts": None,
    }
    conn = None
    try:
        conn = get_pg_connection()
        with conn:
            with conn.cursor() as cur:
                ensure_import_history_table(cur)

                cur.execute(
                    """
                    SELECT imported_at
                    FROM etl_import_history
                    ORDER BY imported_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                state["last_success_at"] = row[0] if row else None

                cur.execute(
                    """
                    SELECT imported_at
                    FROM etl_import_history
                    WHERE import_type = 'full'
                    ORDER BY imported_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                state["last_full_at"] = row[0] if row else None

                cur.execute(
                    """
                    SELECT MAX(source_end_ts)
                    FROM etl_import_history
                    WHERE import_type = 'delta'
                    """
                )
                row = cur.fetchone()
                state["last_delta_end_ts"] = row[0] if row and row[0] is not None else None
    except psycopg2.Error as exc:
        print(
            "Warning: unable to read import state from PostgreSQL. "
            f"Falling back to a first-run state for this extraction. Error: {exc}"
        )
        return state
    finally:
        if conn is not None:
            conn.close()

    return state


def parse_delta_filename(filename: str) -> tuple[int, int] | None:
    values = re.findall(r"(\d{9,})", filename)
    if len(values) < 2:
        return None
    return int(values[0]), int(values[1])


def list_delta_files(session: requests.Session, index_url: str, base_url: str) -> list[dict[str, Any]]:
    response = session.get(index_url, timeout=(15, 120))
    response.raise_for_status()

    entries = []
    for raw_line in response.text.splitlines():
        filename = raw_line.strip()
        if not filename:
            continue
        timestamps = parse_delta_filename(filename)
        if timestamps is None:
            continue
        start_ts, end_ts = timestamps
        entries.append(
            {
                "filename": filename,
                "url": f"{base_url.rstrip('/')}/{filename}",
                "start_ts": start_ts,
                "end_ts": end_ts,
            }
        )

    entries.sort(key=lambda item: item["filename"])
    return entries


def open_text_stream(response: requests.Response, url: str):
    response.raise_for_status()
    response.raw.decode_content = True
    raw_stream = response.raw
    binary_stream = gzip.GzipFile(fileobj=raw_stream) if url.endswith(".gz") else raw_stream
    return io.TextIOWrapper(binary_stream, encoding="utf-8", errors="replace")


def sanitize_filename(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or fallback


def build_download_cache_path(output_path: Path, source_url: str, index: int) -> Path:
    raw_name = Path(urlsplit(source_url).path).name
    filename = sanitize_filename(raw_name, f"source_{index}.dat")
    return output_path.parent / "_downloads" / filename


def get_remote_content_length(session: requests.Session, source_url: str) -> int | None:
    try:
        response = session.head(source_url, allow_redirects=True, timeout=(15, 120))
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        return int(content_length) if content_length else None
    except Exception:
        return None


def validate_gzip_file(path: Path) -> tuple[bool, str | None]:
    try:
        with path.open("rb") as handle:
            magic = handle.read(2)
        if magic != b"\x1f\x8b":
            return False, f"unexpected gzip header {magic!r}"

        with gzip.open(path, "rb") as handle:
            handle.read(1)
        return True, None
    except OSError as exc:
        return False, str(exc)


def download_source_file(session: requests.Session, source_url: str, download_path: Path) -> Path:
    download_path.parent.mkdir(parents=True, exist_ok=True)
    remote_size = get_remote_content_length(session, source_url)

    if download_path.exists() and remote_size is not None and download_path.stat().st_size == remote_size:
        if download_path.suffix == ".gz":
            is_valid, error = validate_gzip_file(download_path)
            if not is_valid:
                print(
                    f"Cached gzip is invalid for {download_path.name} ({error}); "
                    "removing it before retrying download."
                )
                download_path.unlink(missing_ok=True)
            else:
                print(f"Reusing cached download: {download_path.name} ({remote_size} bytes)")
                return download_path
        else:
            print(f"Reusing cached download: {download_path.name} ({remote_size} bytes)")
            return download_path

    for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
        existing_size = download_path.stat().st_size if download_path.exists() else 0
        headers = {}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

        try:
            with session.get(source_url, stream=True, timeout=(30, 600), headers=headers) as response:
                if response.status_code == 416 and remote_size is not None:
                    if download_path.exists() and download_path.stat().st_size >= remote_size:
                        return download_path
                    download_path.unlink(missing_ok=True)
                    continue

                if response.status_code == 403 and existing_size > 0:
                    print(
                        f"Range request forbidden for {download_path.name}; "
                        "removing partial file and retrying without resume."
                    )
                    download_path.unlink(missing_ok=True)
                    continue

                if response.status_code == 206:
                    mode = "ab"
                    appended_from = existing_size
                else:
                    response.raise_for_status()
                    mode = "wb"
                    appended_from = 0
                    if existing_size > 0:
                        print(f"Restarting download from scratch for {download_path.name}")

                with download_path.open(mode) as handle:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            handle.write(chunk)

            final_size = download_path.stat().st_size if download_path.exists() else 0
            if remote_size is not None and final_size < remote_size:
                raise IOError(
                    f"Incomplete download for {source_url}: got {final_size} bytes, expected {remote_size}"
                )
            if download_path.suffix == ".gz":
                is_valid, error = validate_gzip_file(download_path)
                if not is_valid:
                    download_path.unlink(missing_ok=True)
                    raise IOError(f"Downloaded file is not a valid gzip archive: {error}")

            print(
                f"Downloaded source file: {download_path.name} "
                f"(attempt={attempt}, resumed_from={appended_from}, size={final_size})"
            )
            return download_path
        except Exception as exc:
            if attempt >= DOWNLOAD_MAX_ATTEMPTS:
                raise
            wait_seconds = min(30, attempt * 5)
            current_size = download_path.stat().st_size if download_path.exists() else 0
            print(
                f"Download attempt {attempt}/{DOWNLOAD_MAX_ATTEMPTS} failed for {source_url}: {exc}. "
                f"Current_size={current_size}. Retrying in {wait_seconds}s..."
            )
            time.sleep(wait_seconds)

    return download_path


def open_local_text_stream(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def build_full_sample_path(output_path: Path, sample_size: int, sample_strategy: str) -> Path:
    filename = f"{output_path.stem}_raw_sample_{sample_strategy}_{sample_size}.jsonl"
    return output_path.parent / "_samples" / filename


def create_first_n_sample(
    source_path: Path,
    sample_path: Path,
    sample_size: int,
) -> dict[str, int]:
    stats = {"sample_lines_read": 0, "sample_lines_written": 0, "sample_invalid_json_lines": 0}
    sample_path.parent.mkdir(parents=True, exist_ok=True)

    with open_local_text_stream(source_path) as src, sample_path.open("w", encoding="utf-8") as dst:
        for raw_line in src:
            line = raw_line.strip()
            if not line:
                continue

            stats["sample_lines_read"] += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats["sample_invalid_json_lines"] += 1
                continue
            if not isinstance(obj, dict):
                stats["sample_invalid_json_lines"] += 1
                continue

            dst.write(json.dumps(obj, ensure_ascii=False) + "\n")
            stats["sample_lines_written"] += 1
            if stats["sample_lines_written"] >= sample_size:
                break

    return stats


def create_reservoir_sample(
    source_path: Path,
    sample_path: Path,
    sample_size: int,
    seed: int,
) -> dict[str, int]:
    rng = random.Random(seed)
    reservoir: list[str] = []
    stats = {"sample_lines_read": 0, "sample_lines_written": 0, "sample_invalid_json_lines": 0}

    with open_local_text_stream(source_path) as src:
        for raw_line in src:
            line = raw_line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats["sample_invalid_json_lines"] += 1
                continue
            if not isinstance(obj, dict):
                stats["sample_invalid_json_lines"] += 1
                continue

            stats["sample_lines_read"] += 1
            line_json = json.dumps(obj, ensure_ascii=False)
            if len(reservoir) < sample_size:
                reservoir.append(line_json)
            else:
                idx = rng.randint(0, stats["sample_lines_read"] - 1)
                if idx < sample_size:
                    reservoir[idx] = line_json

    sample_path.parent.mkdir(parents=True, exist_ok=True)
    with sample_path.open("w", encoding="utf-8") as dst:
        for row in reservoir:
            dst.write(row + "\n")

    stats["sample_lines_written"] = len(reservoir)
    return stats


def create_local_full_sample(
    source_path: Path,
    sample_path: Path,
    sample_size: int,
    sample_strategy: str,
    sample_seed: int,
) -> dict[str, int]:
    if sample_size <= 0:
        raise ValueError("full sample size must be greater than 0")

    if sample_strategy == "first":
        stats = create_first_n_sample(
            source_path=source_path,
            sample_path=sample_path,
            sample_size=sample_size,
        )
    else:
        stats = create_reservoir_sample(
            source_path=source_path,
            sample_path=sample_path,
            sample_size=sample_size,
            seed=sample_seed,
        )

    print(
        "Created local full sample: "
        f"path={sample_path}, strategy={sample_strategy}, sample_size={sample_size}, "
        f"lines_written={stats['sample_lines_written']}, lines_read={stats['sample_lines_read']}"
    )
    return stats

def process_local_export_file(
    source_path: Path,
    output_handle,
    country: str,
    min_core_nutrients: int,
    stats: dict[str, int],
    max_rows: int | None = None,
) -> bool:
    with open_local_text_stream(source_path) as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                continue
            stats["lines_read"] += 1

            try:
                product = json.loads(line)
            except json.JSONDecodeError:
                stats["invalid_json_lines"] += 1
                continue

            if not isinstance(product, dict):
                stats["invalid_json_lines"] += 1
                continue

            if not has_country(product, country):
                stats["dropped_country"] += 1
                continue
            if not not_empty(product, "code"):
                stats["dropped_code"] += 1
                continue
            if not (not_empty(product, "product_name") or not_empty(product, "product_name_fr")):
                stats["dropped_name"] += 1
                continue
            if not has_category(product):
                stats["dropped_category"] += 1
                continue
            if min_core_nutrients > 0 and count_core_nutrients(product) < min_core_nutrients:
                stats["dropped_nutrition"] += 1
                continue

            output_handle.write(json.dumps(product, ensure_ascii=False) + "\n")
            stats["rows_kept"] += 1
            if max_rows is not None and stats["rows_kept"] >= max_rows:
                return True
    return False


def filter_product(product: dict[str, Any], country: str, min_core_nutrients: int) -> str | None:
    if not has_country(product, country):
        return None
    if not not_empty(product, "code"):
        return None
    if not (not_empty(product, "product_name") or not_empty(product, "product_name_fr")):
        return None
    if not has_category(product):
        return None
    if min_core_nutrients > 0 and count_core_nutrients(product) < min_core_nutrients:
        return None
    return json.dumps(product, ensure_ascii=False)


def stream_export_to_jsonl(
    session: requests.Session,
    source_urls: list[str],
    output_path: Path,
    country: str,
    min_core_nutrients: int,
    max_rows: int | None = None,
) -> dict[str, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if max_rows is not None and max_rows <= 0:
        max_rows = None

    stats = {
        "files_downloaded": 0,
        "lines_read": 0,
        "rows_kept": 0,
        "invalid_json_lines": 0,
        "dropped_country": 0,
        "dropped_code": 0,
        "dropped_name": 0,
        "dropped_category": 0,
        "dropped_nutrition": 0,
    }

    with output_path.open("w", encoding="utf-8") as handle:
        for index, source_url in enumerate(source_urls, start=1):
            download_path = build_download_cache_path(output_path, source_url, index=index)
            local_source = download_source_file(session, source_url, download_path)
            limit_reached = process_local_export_file(
                source_path=local_source,
                output_handle=handle,
                country=country,
                min_core_nutrients=min_core_nutrients,
                stats=stats,
                max_rows=max_rows,
            )
            stats["files_downloaded"] += 1
            if limit_reached:
                break

    return stats


def process_full_export(
    session: requests.Session,
    source_url: str,
    output_path: Path,
    country: str,
    min_core_nutrients: int,
    max_rows: int | None,
    full_mode: str,
    full_sample_size: int,
    full_sample_strategy: str,
    full_sample_seed: int,
) -> dict[str, int]:
    stats = {
        "files_downloaded": 0,
        "lines_read": 0,
        "rows_kept": 0,
        "invalid_json_lines": 0,
        "dropped_country": 0,
        "dropped_code": 0,
        "dropped_name": 0,
        "dropped_category": 0,
        "dropped_nutrition": 0,
        "sample_lines_read": 0,
        "sample_lines_written": 0,
        "sample_invalid_json_lines": 0,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_path = build_download_cache_path(output_path, source_url, index=1)
    local_source = download_source_file(session, source_url, download_path)
    stats["files_downloaded"] = 1

    source_for_filtering = local_source
    if full_mode == "sample":
        sample_path = build_full_sample_path(
            output_path=output_path,
            sample_size=full_sample_size,
            sample_strategy=full_sample_strategy,
        )
        sample_stats = create_local_full_sample(
            source_path=local_source,
            sample_path=sample_path,
            sample_size=full_sample_size,
            sample_strategy=full_sample_strategy,
            sample_seed=full_sample_seed,
        )
        stats.update(sample_stats)
        source_for_filtering = sample_path

    with output_path.open("w", encoding="utf-8") as handle:
        process_local_export_file(
            source_path=source_for_filtering,
            output_handle=handle,
            country=country,
            min_core_nutrients=min_core_nutrients,
            stats=stats,
            max_rows=max_rows,
        )

    return stats


def should_run_full(
    forced_mode: str,
    now_utc: datetime,
    last_success_at: datetime | None,
    last_full_at: datetime | None,
    full_refresh_interval_days: int,
    delta_retention_days: int,
) -> bool:
    if forced_mode == "full":
        return True
    if forced_mode == "delta":
        return False
    if last_full_at is None:
        return True
    if now_utc - last_full_at.astimezone(timezone.utc) >= timedelta(days=full_refresh_interval_days):
        return True
    if last_success_at is not None and now_utc - last_success_at.astimezone(timezone.utc) > timedelta(days=delta_retention_days):
        return True
    return False


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_batch_paths(output_dir: str, import_type: str, suffix: str) -> tuple[Path, str, str]:
    local_dir = Path(output_dir) / "bronze" / "openfood" / import_type
    local_filename = f"openfood_canada_{import_type}_{suffix}.jsonl"
    bronze_key = f"openfood/{import_type}/{local_filename}"
    silver_key = bronze_key.replace(".jsonl", ".parquet")
    return local_dir / local_filename, bronze_key, silver_key


def resolve_local_source_path(local_file: str, output_dir: str) -> Path:
    raw_path = Path(local_file)
    candidates = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(raw_path)
        if local_file.startswith("data/"):
            candidates.append(Path(output_dir) / Path(local_file).relative_to("data"))
        else:
            candidates.append(Path(output_dir) / raw_path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def build_local_source_metadata(local_source: Path, output_dir: str) -> dict[str, Any]:
    local_filename = sanitize_filename(local_source.name, "openfood_local.jsonl")
    bronze_key = f"openfood/local/{local_filename}"
    silver_filename = re.sub(r"\.jsonl(?:\.gz)?$", ".parquet", local_filename)
    if silver_filename == local_filename:
        silver_filename = f"{local_source.stem}.parquet"
    silver_key = f"openfood/local/{silver_filename}"
    return {
        "import_type": "local",
        "local_path": str(local_source),
        "bronze_key": bronze_key,
        "silver_key": silver_key,
        "source_reference": str(local_source),
        "source_start_ts": None,
        "source_end_ts": None,
    }


def extract_official_exports(
    source_mode: str | None = None,
    local_file: str | None = None,
    mode: str = "auto",
    output_dir: str = "/opt/airflow/data",
    country: str = "canada",
    min_core_nutrients: int | None = None,
    full_refresh_interval_days: int | None = None,
    delta_retention_days: int | None = None,
    full_jsonl_url: str | None = None,
    delta_index_url: str | None = None,
    delta_base_url: str | None = None,
    max_rows: int | None = None,
    full_mode: str | None = None,
    full_sample_size: int | None = None,
    full_sample_strategy: str | None = None,
    full_sample_seed: int | None = None,
    delta_max_files: int | None = None,
    **_,
) -> dict[str, Any]:
    if source_mode is None:
        source_mode = env_str("OPENFOOD_SOURCE_MODE", "official")
    if local_file is None:
        local_file = env_str("OPENFOOD_LOCAL_FILE", "")
    if min_core_nutrients is None:
        min_core_nutrients = env_int("OPENFOOD_MIN_CORE_NUTRIENTS", 2)
    if full_refresh_interval_days is None:
        full_refresh_interval_days = env_int("OPENFOOD_FULL_REFRESH_INTERVAL_DAYS", 56)
    if delta_retention_days is None:
        delta_retention_days = env_int("OPENFOOD_DELTA_RETENTION_DAYS", 14)
    if full_jsonl_url is None:
        full_jsonl_url = os.getenv("OPENFOOD_FULL_JSONL_URL", DEFAULT_FULL_JSONL_URL)
    if delta_index_url is None:
        delta_index_url = os.getenv("OPENFOOD_DELTA_INDEX_URL", DEFAULT_DELTA_INDEX_URL)
    if delta_base_url is None:
        delta_base_url = os.getenv("OPENFOOD_DELTA_BASE_URL", DEFAULT_DELTA_BASE_URL)
    if full_mode is None:
        full_mode = env_str("OPENFOOD_FULL_MODE", "direct")
    if full_sample_size is None:
        full_sample_size = env_int("OPENFOOD_FULL_SAMPLE_SIZE", 5000)
    if full_sample_strategy is None:
        full_sample_strategy = env_str("OPENFOOD_FULL_SAMPLE_STRATEGY", "first")
    if full_sample_seed is None:
        full_sample_seed = env_int("OPENFOOD_FULL_SAMPLE_SEED", 42)
    if delta_max_files is None:
        delta_max_files = env_int("OPENFOOD_DELTA_MAX_FILES", 0)
    if max_rows is None:
        max_rows = env_int("OPENFOOD_MAX_ROWS", 500)
    if max_rows <= 0:
        max_rows = None
    if delta_max_files <= 0:
        delta_max_files = None

    if source_mode == "local":
        if not local_file:
            raise ValueError("OPENFOOD_LOCAL_FILE must be set when OPENFOOD_SOURCE_MODE=local")
        local_source = resolve_local_source_path(local_file, output_dir)
        if not local_source.exists():
            raise FileNotFoundError(f"Local source file not found: {local_source}")

        metadata = build_local_source_metadata(local_source, output_dir)
        metadata.update(
            {
                "files_downloaded": 0,
                "lines_read": 0,
                "rows_kept": 0,
                "invalid_json_lines": 0,
                "source_mode": "local",
            }
        )
        print(
            "Local source selected: "
            f"path={metadata['local_path']}, bronze={metadata['bronze_key']}, silver={metadata['silver_key']}"
        )
        return metadata

    now_utc = datetime.now(timezone.utc)
    import_state = get_import_state()
    run_full = should_run_full(
        forced_mode=mode,
        now_utc=now_utc,
        last_success_at=ensure_utc(import_state["last_success_at"]),
        last_full_at=ensure_utc(import_state["last_full_at"]),
        full_refresh_interval_days=full_refresh_interval_days,
        delta_retention_days=delta_retention_days,
    )

    session = make_session(total_retries=6, backoff=1.0)

    if run_full:
        suffix = now_utc.strftime("%Y%m%d")
        output_path, bronze_key, silver_key = build_batch_paths(output_dir, "full", suffix)
        stats = process_full_export(
            session=session,
            source_url=full_jsonl_url,
            output_path=output_path,
            country=country,
            min_core_nutrients=min_core_nutrients,
            max_rows=max_rows,
            full_mode=full_mode,
            full_sample_size=full_sample_size,
            full_sample_strategy=full_sample_strategy,
            full_sample_seed=full_sample_seed,
        )
        metadata = {
            "import_type": "full",
            "local_path": str(output_path),
            "bronze_key": bronze_key,
            "silver_key": silver_key,
            "source_reference": full_jsonl_url,
            "source_start_ts": None,
            "source_end_ts": None,
            "full_mode": full_mode,
            "full_sample_size": full_sample_size if full_mode == "sample" else None,
            "full_sample_strategy": full_sample_strategy if full_mode == "sample" else None,
            **stats,
        }
    else:
        delta_entries = list_delta_files(session=session, index_url=delta_index_url, base_url=delta_base_url)
        last_delta_end_ts = import_state["last_delta_end_ts"] or 0
        pending_entries = [entry for entry in delta_entries if entry["end_ts"] > last_delta_end_ts]
        if delta_max_files is not None:
            pending_entries = pending_entries[:delta_max_files]

        if not pending_entries:
            raise AirflowSkipException("No new delta export to ingest.")

        start_ts = pending_entries[0]["start_ts"]
        end_ts = pending_entries[-1]["end_ts"]
        suffix = f"{start_ts}_{end_ts}"
        output_path, bronze_key, silver_key = build_batch_paths(output_dir, "delta", suffix)
        stats = stream_export_to_jsonl(
            session=session,
            source_urls=[entry["url"] for entry in pending_entries],
            output_path=output_path,
            country=country,
            min_core_nutrients=min_core_nutrients,
            max_rows=max_rows,
        )
        metadata = {
            "import_type": "delta",
            "local_path": str(output_path),
            "bronze_key": bronze_key,
            "silver_key": silver_key,
            "source_reference": ",".join(entry["filename"] for entry in pending_entries),
            "source_start_ts": start_ts,
            "source_end_ts": end_ts,
            "delta_files_selected": len(pending_entries),
            **stats,
        }

    print(
        "Extraction summary: "
        f"import_type={metadata['import_type']}, "
        f"files_downloaded={metadata['files_downloaded']}, "
        f"lines_read={metadata['lines_read']}, "
        f"rows_kept={metadata['rows_kept']}, "
        f"invalid_json_lines={metadata['invalid_json_lines']}"
    )
    if metadata["import_type"] == "full" and metadata.get("full_mode") == "sample":
        print(
            "Full sample summary: "
            f"sample_size={metadata.get('full_sample_size')}, "
            f"sample_strategy={metadata.get('full_sample_strategy')}, "
            f"sample_lines_written={metadata.get('sample_lines_written', 0)}, "
            f"sample_lines_read={metadata.get('sample_lines_read', 0)}"
        )
    print(f"Prepared local Bronze file: {metadata['local_path']}")
    print(f"Planned MinIO keys: bronze={metadata['bronze_key']}, silver={metadata['silver_key']}")
    return metadata


def main():
    args = parse_args()
    extract_official_exports(
        source_mode=args.source_mode,
        local_file=args.local_file,
        mode=args.mode,
        output_dir=args.output_dir,
        country=args.country,
        min_core_nutrients=args.min_core_nutrients,
        full_refresh_interval_days=args.full_refresh_interval_days,
        delta_retention_days=args.delta_retention_days,
        full_jsonl_url=args.full_jsonl_url,
        delta_index_url=args.delta_index_url,
        delta_base_url=args.delta_base_url,
        max_rows=args.max_rows,
        full_mode=args.full_mode,
        full_sample_size=args.full_sample_size,
        full_sample_strategy=args.full_sample_strategy,
        full_sample_seed=args.full_sample_seed,
        delta_max_files=args.delta_max_files,
    )


if __name__ == "__main__":
    main()
