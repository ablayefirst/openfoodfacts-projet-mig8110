#!/usr/bin/env python3
import os
import json
import time
import argparse
from pathlib import Path
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


def parse_args():
    p = argparse.ArgumentParser(description="Extract a sample from OpenFoodFacts API (Bronze JSONL).")
    p.add_argument("--api-url", default=os.getenv("OPENFOOD_API_URL", "https://world.openfoodfacts.org"), help="Base URL")
    p.add_argument("--country", default=os.getenv("OPENFOOD_COUNTRY", "canada"), help="Country filter")
    p.add_argument("--sample-size", type=int, default=int(os.getenv("SAMPLE_SIZE", "500")), help="Number of products")
    p.add_argument("--page-size", type=int, default=100, help="API page size (<=100 is safe)")
    p.add_argument("--output", default="/opt/airflow/data/bronze/openfood_sample.jsonl", help="Local output JSONL path")
    p.add_argument("--sleep", type=float, default=0.8, help="Small delay between pages to be polite")
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


def main():
    args = parse_args()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the correct endpoint from base URL
    # Example base: https://world.openfoodfacts.org
    search_url = args.api_url.rstrip("/") + "/cgi/search.pl"

    wanted = args.sample_size
    page_size = min(args.page_size, 100)

    kept = 0
    page = 1

    print(f"API: {search_url}")
    print(f"Country: {args.country}, Target sample: {wanted}, Page size: {page_size}")
    print(f"Output: {out_path}")

    with out_path.open("w", encoding="utf-8") as f_out:
        session = make_session(total_retries=6, backoff=1.0)
        while kept < wanted:
            params = {
                "search_simple": 1,
                "action": "process",
                "tagtype_0": "countries",
                "tag_contains_0": "contains",
                "tag_0": args.country,
                "page_size": page_size,
                "page": page,
                "json": 1,
            }

            #r = session.get(search_url, params=params, timeout=(10, 180))
            #r.raise_for_status()
            #data = r.json()

            r = session.get(search_url, params=params, timeout=(10, 180))

            if r.status_code != 200:
                print(f"HTTP {r.status_code} from API (page={page}). Retrying after 5s...")
                # petit extrait pour debug sans spammer
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
                # Minimal quality filters (similar spirit to your CSV version)
                if not has_country(prod, args.country):
                    continue
                if not_empty(prod, "code") is False:
                    continue
                if not (not_empty(prod, "product_name") or not_empty(prod, "product_name_fr")):
                    continue
                if not (prod.get("categories_tags") or prod.get("categories")):
                    continue

                f_out.write(json.dumps(prod, ensure_ascii=False) + "\n")
                kept += 1

                if kept >= wanted:
                    break

            print(f"Page {page} done, kept so far: {kept}")
            page += 1
            time.sleep(args.sleep)

    print(f"Done. Wrote {kept} products to {out_path}")

def extract_sample(limit: int = 500, output_dir: str = "/opt/airflow/data", country: str = "canada", **_):
    """
    Airflow wrapper (no argparse).
    """
    output = os.path.join(output_dir, "bronze", "openfood_sample.jsonl")
    # On réutilise ta logique en copiant-collant l'essentiel de main(),
    # ou (moins propre) on force des variables d'env et on appelle main().

    # PROPRE: appelle une version interne qui ne dépend pas de argparse
    # => le plus simple: remplacer parse_args() par des paramètres.
    # Ici je te donne le minimum fiable:
    from pathlib import Path

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    search_url = "https://world.openfoodfacts.org/cgi/search.pl"
    wanted = limit
    page_size = 100
    sleep = 1.0

    kept = 0
    page = 1

    print(f"API: {search_url}")
    print(f"Country: {country}, Target sample: {wanted}, Page size: {page_size}")
    print(f"Output: {out_path}")

    with out_path.open("w", encoding="utf-8") as f_out:
        session = make_session(total_retries=6, backoff=1.0)
        while kept < wanted:
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

            r = session.get(search_url, params=params, timeout=(10, 60))

            if r.status_code != 200:
                print(f"HTTP {r.status_code} page={page} -> retry in 5s")
                time.sleep(5)
                continue

            try:
                data = r.json()
            except Exception as e:
                print(f"JSON decode error page={page}: {e} -> retry in 5s")
                time.sleep(5)
                continue

            products = data.get("products", [])
            if not products:
                print("No more products returned by API. Stopping.")
                break

            for prod in products:
                if not has_country(prod, country):
                    continue
                if not not_empty(prod, "code"):
                    continue
                if not (not_empty(prod, "product_name") or not_empty(prod, "product_name_fr")):
                    continue
                if not (prod.get("categories_tags") or prod.get("categories")):
                    continue

                f_out.write(json.dumps(prod, ensure_ascii=False) + "\n")
                kept += 1
                if kept >= wanted:
                    break

            print(f"Page {page} done, kept so far: {kept}")
            page += 1
            time.sleep(sleep)

    print(f"Done. Wrote {kept} products to {out_path}")


if __name__ == "__main__":
    main()
