#!/usr/bin/env python3
import sys
import csv
import gzip
from pathlib import Path

# Increase CSV field size limit (Open Food Facts can have huge text fields)
csv.field_size_limit(min(sys.maxsize, 10**9))

INPUT_FILE = "data/raw/en.openfoodfacts.org.products.csv.gz"
OUTPUT_FILE = "data/bronze/canada_sample.csv"   # renamed (not necessarily 100k)
TARGET_ROWS = 100_000

def detect_delimiter_gz(gz_path: Path) -> str:
    """
    Detect delimiter by reading the header line from the .csv.gz.
    OFF dumps are often TSV (tab-separated) even if the filename says CSV.
    """
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
    """
    Count how many core nutrition fields are present.
    We use this to keep products that are actually comparable in the app.
    """
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
    # categories_tags is usually better structured than categories (free text)
    return not_empty(row, "categories_tags") or not_empty(row, "categories")

def main():
    input_path = Path(INPUT_FILE)
    output_path = Path(OUTPUT_FILE)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {input_path}")

    in_delim = detect_delimiter_gz(input_path)
    print(f"ℹ Délimiteur détecté pour l'entrée: {'TAB' if in_delim == chr(9) else 'COMMA'}")

    kept = 0

    with gzip.open(input_path, "rt", encoding="utf-8", errors="replace", newline="") as f_in:
        reader = csv.DictReader(f_in, delimiter=in_delim)

        if not reader.fieldnames:
            raise RuntimeError("Impossible de lire l'en-tête (fieldnames vides). Vérifie le fichier/délimiteur.")

        with output_path.open("w", encoding="utf-8", newline="") as f_out:
            writer = csv.DictWriter(f_out, fieldnames=reader.fieldnames, delimiter=",")
            writer.writeheader()

            for row in reader:
                # 1) Canada only
                if not has_canada(row):
                    continue

                # 2) Minimal identity fields
                if not not_empty(row, "code"):
                    continue
                if not not_empty(row, "product_name"):
                    continue

                # 3) Category required (needed for "compare by category")
                if not has_category(row):
                    continue

                # 4) Nutrition comparability:
                # keep product if it has at least 2 core nutrients present
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
