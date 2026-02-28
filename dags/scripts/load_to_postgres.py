#!/usr/bin/env python3
"""
Load Silver Parquet from MinIO into PostgreSQL normalized schema (Gold).

- Keeps BOTH entrypoints:
  - main() for CLI usage
  - load_silver_to_postgres() as Airflow callable (no argparse)

Improvements vs your current version:
- Automatically runs SQL schema file (database/schema/create_tables.sql) before loading
- Uses categories_tags first (fallback categories)
- Normalizes countries/country tags (avoid "Canada" vs "en:canada" duplicates)
- Supports allergens_tags + traces_tags (normalized)
- More robust ingredient parsing (instead of naive comma split)
- Keeps your get_or_create/upsert approach (simple + reliable for small/medium volumes)
"""

import argparse
import ast
import os
import re
from io import BytesIO
from pathlib import Path

import boto3
import pandas as pd
import psycopg2
from botocore.client import Config


# -----------------------------
# CLI
# -----------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Load Silver Parquet from MinIO into PostgreSQL normalized schema."
    )
    p.add_argument("--input-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    p.add_argument("--input-key", required=True, help="Key of the Parquet object in silver bucket")
    # Optional override if you want
    p.add_argument(
        "--schema-sql",
        default=None,
        help="Path to SQL schema file (default: database/schema/create_tables.sql)",
    )
    return p.parse_args()


# -----------------------------
# Clients
# -----------------------------
def get_s3_client():
    endpoint = os.environ["MINIO_ENDPOINT"].strip()
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        endpoint_url = endpoint
    else:
        scheme = "https" if secure else "http"
        endpoint_url = f"{scheme}://{endpoint}"

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def get_pg_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "openfood_db"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres123"),
    )


# -----------------------------
# Cleaning / parsing helpers
# -----------------------------
def is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def clean_text(value):
    if is_missing(value):
        return None
    txt = str(value).replace("\x00", "").strip()
    if txt.lower() in {"nan", "none", "null"}:
        return None
    return txt


def clean_float(value):
    if is_missing(value):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def clean_int(value):
    if is_missing(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_code(value):
    txt = clean_text(value)
    if txt is None:
        return None
    if txt.endswith(".0"):
        try:
            return str(int(float(txt)))
        except ValueError:
            return txt
    return txt


def normalize_nutrition_grade(value):
    """
    Keep only valid Nutri-Score letters for CHAR(1) column.
    Accepts values like: "a", "A", "en:a", "nutriscore-a".
    Returns one lowercase letter in a-e, or None.
    """
    txt = clean_text(value)
    if txt is None:
        return None

    txt = txt.strip().lower()
    if ":" in txt:
        txt = txt.split(":")[-1]

    match = re.search(r"[a-e]", txt)
    if not match:
        return None
    return match.group(0)


def normalize_tag(value: str) -> str | None:
    """
    Normalize tags like:
      - 'en:canada' -> 'canada'
      - 'fr:boissons' -> 'boissons'
    Also trims/lowers for stable deduplication.
    """
    txt = clean_text(value)
    if txt is None:
        return None
    txt = txt.strip()
    if ":" in txt:
        txt = txt.split(":", 1)[1]
    txt = txt.strip().lower()
    return txt if txt else None


def split_values(value):
    """
    Generic splitter for:
      - list fields
      - CSV-like strings
      - stringified lists "['a','b']"
    """
    if is_missing(value):
        return []

    raw_items = []
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    elif isinstance(value, str):
        txt = value.strip()
        if not txt:
            return []
        if txt.startswith("[") and txt.endswith("]"):
            try:
                parsed = ast.literal_eval(txt)
                if isinstance(parsed, (list, tuple, set)):
                    raw_items = list(parsed)
                else:
                    raw_items = [txt]
            except (SyntaxError, ValueError):
                raw_items = [part.strip() for part in txt.split(",")]
        else:
            raw_items = [part.strip() for part in txt.split(",")]
    else:
        raw_items = [value]

    seen = set()
    cleaned = []
    for item in raw_items:
        txt = clean_text(item)
        if txt is None:
            continue
        if txt not in seen:
            seen.add(txt)
            cleaned.append(txt)
    return cleaned


def parse_ingredients_text(text: str | None, max_items: int = 60) -> list[str]:
    """
    More robust ingredient parsing than simple comma split:
    - remove parentheses content
    - remove percentages and numbers
    - split on commas/semicolons
    - keep clean tokens
    """
    txt = clean_text(text)
    if txt is None:
        return []

    t = txt.lower()
    t = re.sub(r"\([^)]*\)", " ", t)          # remove ( ... )
    t = re.sub(r"\d+(\.\d+)?\s*%?", " ", t)   # remove 5%, 10, 2.5%
    t = t.replace("•", ",")
    parts = re.split(r"[;,]", t)

    cleaned = []
    seen = set()
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # keep letters (incl accents), spaces, hyphens and apostrophes
        p = re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ \-']", " ", p)
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) < 3:
            continue
        # avoid generic garbage tokens
        if p in {"ingredients", "ingrédients"}:
            continue
        if p not in seen:
            seen.add(p)
            cleaned.append(p)
        if len(cleaned) >= max_items:
            break

    return cleaned


def derive_quantity_text(row: pd.Series) -> str | None:
    """
    Prefer normalized `quantity` from silver.
    Fallback to composed "<value> <unit>" when split columns are present.
    """
    quantity = clean_text(row.get("quantity"))
    if quantity:
        return quantity

    value = clean_float(row.get("quantity_value"))
    unit = clean_text(row.get("quantity_unit"))
    if value is None or unit is None:
        return None
    return f"{value:g} {unit}"


def derive_energy_kcal_100g(row: pd.Series) -> float | None:
    """
    Prefer explicit kcal from silver.
    Fallback to kJ fields converted to kcal when needed.
    """
    kcal = clean_float(row.get("energy_kcal_100g"))
    if kcal is not None:
        return kcal

    energy_kj = clean_float(row.get("energy_kj_100g"))
    if energy_kj is None:
        energy_kj = clean_float(row.get("energy_100g"))
    if energy_kj is None:
        return None
    return round(energy_kj / 4.184, 1)


def derive_salt_100g(row: pd.Series) -> float | None:
    """
    Prefer salt directly.
    Fallback to sodium converted to salt when salt is missing.
    In silver PR2, sodium_100g is in grams and salt = sodium * 2.5.
    """
    salt = clean_float(row.get("salt_100g"))
    if salt is not None:
        return salt

    sodium = clean_float(row.get("sodium_100g"))
    if sodium is None:
        return None
    return round(sodium * 2.5, 4)


# -----------------------------
# Schema execution
# -----------------------------
def resolve_default_schema_path() -> str:
    """
    We expect repo layout like:
      dags/
        scripts/
          load_to_postgres.py   (this file)
      database/
        schema/
          create_tables.sql

    From dags/scripts -> go up 2 levels to repo root.
    """
    here = Path(__file__).resolve()
    dags_root = here.parents[1]  # dags/scripts/<file> -> dags -> repo_root
    return str(dags_root / "sql" / "create_tables.sql")


def ensure_schema(cur, schema_sql_path: str | None = None):
    path = schema_sql_path or resolve_default_schema_path()
    path = str(Path(path).resolve())

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Schema SQL file not found at: {path}\n"
            f"Tip: verify your repo structure or pass --schema-sql / schema_sql_path."
        )

    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()

    # psycopg2 can execute multi-statement scripts
    cur.execute(sql)
    print(f"Schema ensured using SQL file: {path}")


# -----------------------------
# DB helpers
# -----------------------------
def get_or_create(cur, table: str, id_col: str, value_col: str, value: str):
    cur.execute(
        f"SELECT {id_col} FROM {table} WHERE {value_col} = %s LIMIT 1",
        (value,),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        f"INSERT INTO {table} ({value_col}) VALUES (%s) RETURNING {id_col}",
        (value,),
    )
    return cur.fetchone()[0]


def upsert_product(cur, row: pd.Series, marque_id):
    cur.execute(
        """
        INSERT INTO produit (
            code_produit,
            nom_produit,
            quantite,
            nutrition_grade,
            nutriscore_score,
            nova_group,
            url,
            image_url,
            image_small_url,
            image_ingredients_url,
            image_ingredients_small_url,
            image_nutrition_url,
            id_marque
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (code_produit) DO UPDATE SET
            nom_produit = COALESCE(EXCLUDED.nom_produit, produit.nom_produit),
            quantite = COALESCE(EXCLUDED.quantite, produit.quantite),
            nutrition_grade = COALESCE(EXCLUDED.nutrition_grade, produit.nutrition_grade),
            nutriscore_score = COALESCE(EXCLUDED.nutriscore_score, produit.nutriscore_score),
            nova_group = COALESCE(EXCLUDED.nova_group, produit.nova_group),
            url = COALESCE(EXCLUDED.url, produit.url),
            image_url = COALESCE(EXCLUDED.image_url, produit.image_url),
            image_small_url = COALESCE(EXCLUDED.image_small_url, produit.image_small_url),
            image_ingredients_url = COALESCE(EXCLUDED.image_ingredients_url, produit.image_ingredients_url),
            image_ingredients_small_url = COALESCE(EXCLUDED.image_ingredients_small_url, produit.image_ingredients_small_url),
            image_nutrition_url = COALESCE(EXCLUDED.image_nutrition_url, produit.image_nutrition_url),
            id_marque = COALESCE(EXCLUDED.id_marque, produit.id_marque)
        """,
        (
            normalize_code(row.get("code")),
            clean_text(row.get("product_name")),
            derive_quantity_text(row),
            normalize_nutrition_grade(row.get("nutriscore_grade")),
            clean_int(row.get("nutriscore_score")),
            clean_int(row.get("nova_group")),
            clean_text(row.get("url")),
            clean_text(row.get("image_url")),
            clean_text(row.get("image_small_url")),
            clean_text(row.get("image_ingredients_url")),
            clean_text(row.get("image_ingredients_small_url")),
            clean_text(row.get("image_nutrition_url")),
            marque_id,
        ),
    )


def upsert_nutrition(cur, row: pd.Series):
    cur.execute(
        """
        INSERT INTO valeurs_nutritionnelles (
            code_produit,
            energy_kcal_100g,
            saturated_fat_100g,
            sugars_100g,
            fiber_100g,
            proteins_100g,
            salt_100g,
            carbohydrates_100g,
            fat_100g
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (code_produit) DO UPDATE SET
            energy_kcal_100g = COALESCE(EXCLUDED.energy_kcal_100g, valeurs_nutritionnelles.energy_kcal_100g),
            saturated_fat_100g = COALESCE(EXCLUDED.saturated_fat_100g, valeurs_nutritionnelles.saturated_fat_100g),
            sugars_100g = COALESCE(EXCLUDED.sugars_100g, valeurs_nutritionnelles.sugars_100g),
            fiber_100g = COALESCE(EXCLUDED.fiber_100g, valeurs_nutritionnelles.fiber_100g),
            proteins_100g = COALESCE(EXCLUDED.proteins_100g, valeurs_nutritionnelles.proteins_100g),
            salt_100g = COALESCE(EXCLUDED.salt_100g, valeurs_nutritionnelles.salt_100g),
            carbohydrates_100g = COALESCE(EXCLUDED.carbohydrates_100g, valeurs_nutritionnelles.carbohydrates_100g),
            fat_100g = COALESCE(EXCLUDED.fat_100g, valeurs_nutritionnelles.fat_100g)
        """,
        (
            normalize_code(row.get("code")),
            derive_energy_kcal_100g(row),
            clean_float(row.get("saturated_fat_100g")),
            clean_float(row.get("sugars_100g")),
            clean_float(row.get("fiber_100g")),
            clean_float(row.get("proteins_100g")),
            derive_salt_100g(row),
            clean_float(row.get("carbohydrates_100g")),
            clean_float(row.get("fat_100g")),
        ),
    )


def insert_link(cur, table: str, id_col: str, code_produit: str, entity_id):
    cur.execute(
        f"INSERT INTO {table} (code_produit, {id_col}) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (code_produit, entity_id),
    )
    return cur.rowcount > 0


# -----------------------------
# Core loader
# -----------------------------
def load_dataframe_to_postgres(df: pd.DataFrame, schema_sql_path: str | None = None) -> dict[str, int]:
    if df.empty:
        print("No rows to load from Silver Parquet.")
        return {
            "rows_input": 0,
            "rows_loaded": 0,
            "rows_skipped_missing_keys": 0,
            "products_inserted": 0,
            "products_updated": 0,
            "nutrition_inserted": 0,
            "nutrition_updated": 0,
            "links_inserted": 0,
        }

    conn = get_pg_connection()
    stats = {
        "rows_input": len(df),
        "rows_loaded": 0,
        "rows_skipped_missing_keys": 0,
        "products_inserted": 0,
        "products_updated": 0,
        "nutrition_inserted": 0,
        "nutrition_updated": 0,
        "links_inserted": 0,
    }

    # Small in-memory caches to reduce repeated SELECTs
    cache_marque = {}
    cache_categorie = {}
    cache_pays = {}
    cache_label = {}
    cache_ingredient = {}
    cache_allergene = {}

    try:
        with conn:
            with conn.cursor() as cur:
                # Ensure schema exists (safe even if already created)
                ensure_schema(cur, schema_sql_path=schema_sql_path)

                for _, row in df.iterrows():
                    code = normalize_code(row.get("code"))
                    product_name = clean_text(row.get("product_name"))

                    if not code or not product_name:
                        stats["rows_skipped_missing_keys"] += 1
                        continue

                    # ---- Brand (marque)
                    brand = clean_text(row.get("brands"))
                    marque_id = None
                    if brand:
                        if brand in cache_marque:
                            marque_id = cache_marque[brand]
                        else:
                            marque_id = get_or_create(cur, "marque", "id_marque", "brands", brand)
                            cache_marque[brand] = marque_id

                    # ---- Existing state (for metrics)
                    cur.execute("SELECT 1 FROM produit WHERE code_produit = %s LIMIT 1", (code,))
                    product_exists = cur.fetchone() is not None
                    cur.execute(
                        "SELECT 1 FROM valeurs_nutritionnelles WHERE code_produit = %s LIMIT 1",
                        (code,),
                    )
                    nutrition_exists = cur.fetchone() is not None

                    # ---- Produit + Nutrition
                    upsert_product(cur, row, marque_id)
                    upsert_nutrition(cur, row)
                    if product_exists:
                        stats["products_updated"] += 1
                    else:
                        stats["products_inserted"] += 1
                    if nutrition_exists:
                        stats["nutrition_updated"] += 1
                    else:
                        stats["nutrition_inserted"] += 1

                    # ---- Categories: prefer categories_tags then categories
                    categories = split_values(row.get("categories_tags"))
                    if not categories:
                        categories = split_values(row.get("categories"))
                    for cat in categories:
                        cat_txt = clean_text(cat)
                        if not cat_txt:
                            continue
                        if cat_txt in cache_categorie:
                            cat_id = cache_categorie[cat_txt]
                        else:
                            cat_id = get_or_create(cur, "categorie", "id_categorie", "categorie", cat_txt)
                            cache_categorie[cat_txt] = cat_id
                        if insert_link(cur, "produit_categorie", "id_categorie", code, cat_id):
                            stats["links_inserted"] += 1

                    # ---- Ingredients: parse ingredients_text (robust)
                    ingredients = parse_ingredients_text(row.get("ingredients_text"))
                    for ing in ingredients:
                        if ing in cache_ingredient:
                            ing_id = cache_ingredient[ing]
                        else:
                            ing_id = get_or_create(cur, "ingredient", "id_ingredient", "ingredients_nom", ing)
                            cache_ingredient[ing] = ing_id
                        if insert_link(cur, "produit_ingredient", "id_ingredient", code, ing_id):
                            stats["links_inserted"] += 1

                    # ---- Countries: prefer countries_tags then countries; normalize tags
                    country_values = split_values(row.get("countries_tags"))
                    if not country_values:
                        country_values = split_values(row.get("countries"))

                    seen_countries = set()
                    for country in country_values:
                        norm = normalize_tag(country)
                        if not norm or norm in seen_countries:
                            continue
                        seen_countries.add(norm)

                        if norm in cache_pays:
                            country_id = cache_pays[norm]
                        else:
                            country_id = get_or_create(cur, "pays", "id_pays", "countries_en", norm)
                            cache_pays[norm] = country_id
                        if insert_link(cur, "produit_pays", "id_pays", code, country_id):
                            stats["links_inserted"] += 1

                    # ---- Labels: prefer labels_tags (already list in silver)
                    for label in split_values(row.get("labels_tags")):
                        lab = normalize_tag(label) or clean_text(label)
                        if not lab:
                            continue
                        if lab in cache_label:
                            label_id = cache_label[lab]
                        else:
                            label_id = get_or_create(cur, "label", "label_id", "labels", lab)
                            cache_label[lab] = label_id
                        if insert_link(cur, "produit_label", "label_id", code, label_id):
                            stats["links_inserted"] += 1

                    # ---- Allergens: allergens_tags + traces_tags (normalized)
                    allergen_values = split_values(row.get("allergens_tags")) + split_values(row.get("traces_tags"))
                    seen_all = set()
                    for allergen in allergen_values:
                        a = normalize_tag(allergen) or clean_text(allergen)
                        if not a or a in seen_all:
                            continue
                        seen_all.add(a)

                        if a in cache_allergene:
                            allergen_id = cache_allergene[a]
                        else:
                            allergen_id = get_or_create(cur, "allergene", "allergen_id", "allergens", a)
                            cache_allergene[a] = allergen_id
                        if insert_link(cur, "produit_allergene", "allergen_id", code, allergen_id):
                            stats["links_inserted"] += 1

                    stats["rows_loaded"] += 1
    finally:
        conn.close()

    print(
        "Load summary: "
        f"rows_input={stats['rows_input']}, rows_loaded={stats['rows_loaded']}, "
        f"rows_skipped_missing_keys={stats['rows_skipped_missing_keys']}, "
        f"products_inserted={stats['products_inserted']}, products_updated={stats['products_updated']}, "
        f"nutrition_inserted={stats['nutrition_inserted']}, nutrition_updated={stats['nutrition_updated']}, "
        f"links_inserted={stats['links_inserted']}"
    )
    return stats


# -----------------------------
# Airflow callable
# -----------------------------
def load_silver_to_postgres(
    input_key: str,
    input_bucket: str = None,
    schema_sql_path: str | None = None,
    **_,
):
    """
    Airflow wrapper (no argparse).
    - Reads Silver Parquet from MinIO
    - Ensures schema from database/schema/create_tables.sql
    - Loads into Postgres normalized schema
    """
    if input_bucket is None:
        input_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")

    s3 = get_s3_client()
    obj = s3.get_object(Bucket=input_bucket, Key=input_key)
    parquet_bytes = obj["Body"].read()

    df = pd.read_parquet(BytesIO(parquet_bytes))
    stats = load_dataframe_to_postgres(df, schema_sql_path=schema_sql_path)

    print(f"Loaded {stats['rows_loaded']} products into PostgreSQL from s3://{input_bucket}/{input_key}")
    return {"loaded_rows": stats["rows_loaded"], "bucket": input_bucket, "key": input_key, **stats}


# -----------------------------
# CLI entry
# -----------------------------
def main():
    args = parse_args()
    load_silver_to_postgres(
        input_bucket=args.input_bucket,
        input_key=args.input_key,
        schema_sql_path=args.schema_sql,
    )


if __name__ == "__main__":
    main()
