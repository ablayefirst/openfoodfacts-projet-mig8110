#!/usr/bin/env python3
import os
import json
import time
import argparse
from pathlib import Path
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry



DEFAULT_API_URL = "https://world.openfoodfacts.org/cgi/search.pl"


def not_empty(obj, key: str) -> bool:
    v = obj.get(key)
    return v is not None and str(v).strip() != ""


def has_country(product: dict, country: str) -> bool:
    country = country.lower()
    countries = (product.get("countries") or "").lower()
    tags = [t.lower() for t in (product.get("countries_tags") or [])]
    return (country in countries) or (f"en:{country}" in tags)


def value_present(value: Any) -> bool:
    if value is None:
        return False
    txt = str(value).strip()
    if not txt:
        return False
    return txt.lower() not in {"nan", "none", "null"}


def nutrient_present(product: dict, *keys: str) -> bool:
    nutriments = product.get("nutriments") or {}
    if not isinstance(nutriments, dict):
        nutriments = {}

    for key in keys:
        if value_present(product.get(key)) or value_present(nutriments.get(key)):
            return True
    return False


def count_core_nutrients(product: dict) -> int:
    count = 0
    if nutrient_present(product, "energy-kcal_100g", "energy_kcal_100g", "energy_100g"):
        count += 1
    if nutrient_present(product, "sugars_100g"):
        count += 1
    if nutrient_present(product, "fat_100g"):
        count += 1
    if nutrient_present(product, "salt_100g"):
        count += 1
    return count


def has_category(product: dict) -> bool:
    return bool(product.get("categories_tags") or product.get("categories"))


def parse_args():
    p = argparse.ArgumentParser(description="Extract a sample from OpenFoodFacts API (Bronze JSONL).")
    p.add_argument("--api-url", default=os.getenv("OPENFOOD_API_URL", "https://world.openfoodfacts.org"), help="Base URL")
    p.add_argument("--country", default=os.getenv("OPENFOOD_COUNTRY", "canada"), help="Country filter")
    p.add_argument("--sample-size", type=int, default=int(os.getenv("SAMPLE_SIZE", "500")), help="Number of products")
    p.add_argument("--page-size", type=int, default=100, help="API page size (<=100 is safe)")
    p.add_argument("--output", default="/opt/airflow/data/bronze/openfood_sample.jsonl", help="Local output JSONL path")
    p.add_argument("--sleep", type=float, default=0.8, help="Small delay between pages to be polite")
    p.add_argument(
        "--min-core-nutrients",
        type=int,
        default=int(os.getenv("OPENFOOD_MIN_CORE_NUTRIENTS", "2")),
        help="Minimum number of core nutrients present among energy/sugars/fat/salt (0 disables filter)",
    )
    return p.parse_args()

def make_session(total_retries: int = 6, backoff: float = 1.0) -> requests.Session:
    """
    Create a requests session with retries + exponential backoff.
    """
    session = requests.Session()
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


def run_extraction(
    search_url: str,
    country: str,
    wanted: int,
    page_size: int,
    output_path: Path,
    sleep_seconds: float,
    min_core_nutrients: int,
    timeout: tuple[int, int],
) -> dict[str, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page_size = max(1, min(page_size, 100))
    min_core_nutrients = max(0, min_core_nutrients)

    stats = {
        "scanned": 0,
        "kept": 0,
        "dropped_country": 0,
        "dropped_code": 0,
        "dropped_name": 0,
        "dropped_category": 0,
        "dropped_nutrition": 0,
    }
    page = 1

    print(f"API: {search_url}")
    print(
        f"Country: {country}, Target sample: {wanted}, Page size: {page_size}, "
        f"Min core nutrients: {min_core_nutrients}"
    )
    print(f"Output: {output_path}")

    with output_path.open("w", encoding="utf-8") as f_out:
        session = make_session(total_retries=6, backoff=1.0)
        while stats["kept"] < wanted:
            params = {
                "search_simple": 1,
                "action": "process",
                "tagtype_0": "countries",
                "tag_contains_0": "contains",
                "tag_0": country,
                "page_size": page_size,
                "page": page,
                "json": 1,
            }

            r = session.get(search_url, params=params, timeout=timeout)

            if r.status_code != 200:
                print(f"HTTP {r.status_code} from API (page={page}). Retrying after 5s...")
                print(r.text[:200])
                time.sleep(5)
                continue

            try:
                data = r.json()
            except Exception as e:
                print(f"Failed to decode JSON (page={page}): {e}. Retrying after 5s...")
                time.sleep(5)
                continue

            products = data.get("products", [])
            if not products:
                print("No more products returned by API. Stopping.")
                break

            for prod in products:
                stats["scanned"] += 1

                if not has_country(prod, country):
                    stats["dropped_country"] += 1
                    continue
                if not not_empty(prod, "code"):
                    stats["dropped_code"] += 1
                    continue
                if not (not_empty(prod, "product_name") or not_empty(prod, "product_name_fr")):
                    stats["dropped_name"] += 1
                    continue
                if not has_category(prod):
                    stats["dropped_category"] += 1
                    continue
                if min_core_nutrients > 0 and count_core_nutrients(prod) < min_core_nutrients:
                    stats["dropped_nutrition"] += 1
                    continue

                f_out.write(json.dumps(prod, ensure_ascii=False) + "\n")
                stats["kept"] += 1

                if stats["kept"] >= wanted:
                    break

            print(f"Page {page} done, kept so far: {stats['kept']}")
            page += 1
            time.sleep(sleep_seconds)

    print(f"Done. Wrote {stats['kept']} products to {output_path}")
    print(
        "Quality summary: "
        f"scanned={stats['scanned']}, kept={stats['kept']}, "
        f"dropped_country={stats['dropped_country']}, dropped_code={stats['dropped_code']}, "
        f"dropped_name={stats['dropped_name']}, dropped_category={stats['dropped_category']}, "
        f"dropped_nutrition={stats['dropped_nutrition']}"
    )
    return stats


def main():
    args = parse_args()
    search_url = args.api_url.rstrip("/") + "/cgi/search.pl"
    run_extraction(
        search_url=search_url,
        country=args.country,
        wanted=args.sample_size,
        page_size=args.page_size,
        output_path=Path(args.output),
        sleep_seconds=args.sleep,
        min_core_nutrients=args.min_core_nutrients,
        timeout=(10, 180),
    )

def extract_sample(
    limit: int = 500,
    output_dir: str = "/opt/airflow/data",
    country: str = "canada",
    min_core_nutrients: int | None = None,
    **_,
):
    """
    Airflow wrapper (no argparse).
    """
    if min_core_nutrients is None:
        min_core_nutrients = int(os.getenv("OPENFOOD_MIN_CORE_NUTRIENTS", "2"))

    return run_extraction(
        search_url=DEFAULT_API_URL,
        country=country,
        wanted=limit,
        page_size=100,
        output_path=Path(os.path.join(output_dir, "bronze", "openfood_sample.jsonl")),
        sleep_seconds=1.0,
        min_core_nutrients=min_core_nutrients,
        timeout=(10, 60),
    )


if __name__ == "__main__":
    main()
