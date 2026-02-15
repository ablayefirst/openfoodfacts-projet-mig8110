#!/usr/bin/env python3
import sys
import csv
import gzip
import urllib.request
from pathlib import Path

# Increase CSV field size limit
csv.field_size_limit(min(sys.maxsize, 10**9))

DOWNLOAD_URL = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"
INPUT_FILE = "data/raw/en.openfoodfacts.org.products.csv.gz"
OUTPUT_FILE = "data/bronze/canada_sample.csv"
TARGET_ROWS = 100_000


# ----------------------------
# DOWNLOAD FUNCTION
# ----------------------------
def download_if_needed(url: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        print(" Fichier déjà présent, téléchargement ignoré.")
        return

    print("⬇ Téléchargement du dataset Open Food Facts...")
    urllib.request.urlretrieve(url, destination)
    print(" Téléchargement terminé.")


# ----------------------------
# EXISTING FUNCTIONS (unchanged)
# ----------------------------
def detect_delimiter_gz(gz_path: Path) -> str:
    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace", newline="") as f:
        header = f.readline()
    return "\t" if header.count("\t") > header.count(",") else ","


def not_empty(row: dict, key: str) -> bool:
    v = row.get(key)
    return v is not None and str(v).strip() != ""


def has_canada(row: dict) -> bool:
    countries = (row.get("countries") or "").lower()
    countries_tags = (row.get("countries_tags") or "").lower()
    return ("canada" in countries) or ("en:canada" in countries_tags)


def energy_present(row: dict) -> bool:
    return not_empty(row, "energy-kcal_100g") or not_empty(row, "energy_kcal_100g")


def count_core_nutrients(row: dict) -> int:
    count = 0
    if energy_present(row):
        count += 1
    if not_empty(row, "sugars_100g"):
        count += 1
    if not_empty(row, "fat_100g"):
        count += 1
    if not_empty(row, "salt_100g"):
        count += 1
    return count


def has_category(row: dict) -> bool:
    return not_empty(row, "categories_tags") or not_empty(row, "categories")


# ----------------------------
# MAIN
# ----------------------------
def main():
    input_path = Path(INPUT_FILE)
    output_path = Path(OUTPUT_FILE)

    #  Download dataset automatically
    download_if_needed(DOWNLOAD_URL, input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    in_delim = detect_delimiter_gz(input_path)
    print(f"ℹ Délimiteur détecté : {'TAB' if in_delim == chr(9) else 'COMMA'}")

    kept = 0

    with gzip.open(input_path, "rt", encoding="utf-8", errors="replace", newline="") as f_in:
        reader = csv.DictReader(f_in, delimiter=in_delim)

        with output_path.open("w", encoding="utf-8", newline="") as f_out:
            writer = csv.DictWriter(f_out, fieldnames=reader.fieldnames, delimiter=",")
            writer.writeheader()

            for row in reader:

                if not has_canada(row):
                    continue

                if not not_empty(row, "code"):
                    continue

                if not not_empty(row, "product_name"):
                    continue

                if not has_category(row):
                    continue

                if count_core_nutrients(row) < 2:
                    continue

                writer.writerow(row)
                kept += 1

                if kept % 10_000 == 0:
                    print(f" Progress: {kept} lignes écrites...")

                if kept >= TARGET_ROWS:
                    break

    print(f" Terminé : {kept} lignes écrites dans {output_path}")


if __name__ == "__main__":
    main()
