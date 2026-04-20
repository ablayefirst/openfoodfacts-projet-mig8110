#!/usr/bin/env python3
import argparse
import gzip
import json
import os
from pathlib import Path
from typing import Any

# =========================
# UTILS
# =========================

def not_empty(obj: dict[str, Any], key: str) -> bool:
    value = obj.get(key)
    return value is not None and str(value).strip() != ""


def has_category(product: dict[str, Any]) -> bool:
    return bool(product.get("categories_tags") or product.get("categories"))


def count_core_nutrients(product: dict[str, Any]) -> int:
    nutriments = product.get("nutriments") or {}
    count = 0

    for key in ["energy_100g", "sugars_100g", "fat_100g", "salt_100g"]:
        if nutriments.get(key) is not None:
            count += 1

    return count


def open_local_text_stream(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


# =========================
# 🔥 VERSION OPTIMISÉE
# =========================

def process_local_export_file(
    source_path: Path,
    output_handle,
    country: str,
    min_core_nutrients: int,
    stats: dict[str, int],
    max_rows: int | None = None,
) -> bool:

    scanned = 0
    max_scan = max_rows * 500 if max_rows else 50000 # 🔥 CRITIQUE pour éviter les zombies

    country_tag = f"en:{country.lower().replace(' ', '-')}"

    print(f"[INFO] Start processing file: {source_path}")

    with open_local_text_stream(source_path) as stream:
        for raw_line in stream:
            scanned += 1

            # 🔥 LOG DEBUG
            if scanned % 500 == 0:
                print(f"[DEBUG] scanned={scanned}, kept={stats['rows_kept']}")

            # 🔥 STOP HARD
            if scanned >= max_scan:
                print("[INFO] Max scan reached → stopping early")
                return True

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

            # 🔥 COUNTRY FILTER OPTIMISÉ
            tags = [str(t).lower() for t in (product.get("countries_tags") or [])]
            if country_tag not in tags:
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

            # ✅ KEEP
            output_handle.write(json.dumps(product) + "\n")
            stats["rows_kept"] += 1

            # 🔥 STOP EARLY
            if max_rows is not None and stats["rows_kept"] >= max_rows:
                print("[INFO] Max rows reached → stopping")
                return True

    return False


# =========================
# 🎯 MAIN FUNCTION AIRFLOW
# =========================

def extract_official_exports(
    source_mode: str = None,
    local_file: str = None,
    output_dir: str = "/opt/airflow/data",
    country: str = "united states",
    min_core_nutrients: int = 1,
    max_rows: int = 10,
    **_,
):

    if source_mode is None:
        source_mode = os.getenv("OPENFOOD_SOURCE_MODE", "local")

    if local_file is None:
        local_file = os.getenv("OPENFOOD_LOCAL_FILE")

    if not local_file:
        raise ValueError("OPENFOOD_LOCAL_FILE must be defined")

    local_path = Path(local_file)

    if not local_path.is_absolute():
        local_path = Path(output_dir) / local_file

    if not local_path.exists():
        raise FileNotFoundError(f"File not found: {local_path}")

    print(f"[INFO] Using LOCAL file: {local_path}")

    output_path = Path(output_dir) / "bronze" / "openfood" / "local" / "openfood_local.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    stats = {
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
        process_local_export_file(
            source_path=local_path,
            output_handle=handle,
            country=country,
            min_core_nutrients=min_core_nutrients,
            stats=stats,
            max_rows=max_rows,
        )

    print(f"[INFO] DONE → kept={stats['rows_kept']} rows")

    return {
        "import_type": "local",
        "local_path": str(output_path),
        "bronze_key": "openfood/local/openfood_local.jsonl",
        "silver_key": "openfood/local/openfood_local.parquet",
        **stats,
    }


# =========================
# CLI
# =========================

def main():
    extract_official_exports()


if __name__ == "__main__":
    main()