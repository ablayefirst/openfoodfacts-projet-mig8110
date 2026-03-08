#!/usr/bin/env python3
import argparse
import ast
import copy
import json
import os
import re
import unicodedata
from io import BytesIO
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
from botocore.client import Config

try:
    import yaml
except ImportError:
    yaml = None


GRADE_TO_SCORE = {"a": -1, "b": 1, "c": 7, "d": 15, "e": 19}

DEFAULT_NORMALIZATION_RULES = {
    "ingredients": {
        "blacklist_exact": [
            "unknown",
            "unknow",
            "none",
            "null",
            "n/a",
            "ingredients",
            "ingredient",
            "ingredients text",
        ],
        "blacklist_contains": ["may contain", "peut contenir", "traces de"],
        "remove_words": ["ingredients", "ingredient", "contains"],
        "corrections": {},
        "standardization": {},
    },
    "categories": {
        "blacklist_exact": ["unknown", "unknow", "none", "null", "n/a"],
        "blacklist_contains": [],
        "remove_words": [],
        "corrections": {},
        "standardization": {},
    },
}

OUTPUT_COLUMNS = [
    "code",
    "product_name",
    "brands",
    "quantity",
    "quantity_value",
    "quantity_unit",
    "url",
    "labels_tags",
    "categories",
    "categories_tags",
    "nutriscore_grade",
    "nutriscore_score",
    "nova_group",
    "energy_100g",
    "energy_kj_100g",
    "energy_kcal_100g",
    "fat_100g",
    "saturated_fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
    "ingredients_text",
    "allergens_tags",
    "traces_tags",
    "countries",
    "countries_tags",
    "image_url",
    "image_small_url",
    "image_ingredients_url",
    "image_ingredients_small_url",
    "image_nutrition_url",
]


def parse_args():
    p = argparse.ArgumentParser(description="Transform Bronze JSONL in MinIO to Silver Parquet in MinIO.")
    p.add_argument("--input-bucket", default=os.getenv("MINIO_BUCKET_BRONZE", "bronze"))
    p.add_argument("--input-key", required=True, help="Key of the JSONL object in bronze bucket")
    p.add_argument("--output-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    p.add_argument("--output-key", required=True, help="Key of the Parquet object in silver bucket")
    return p.parse_args()


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


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return True
        if txt.lower() in {"nan", "none", "null"}:
            return True
    return False


def value_present(value: Any) -> bool:
    if is_missing(value):
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def clean_text(value: Any) -> str | None:
    if is_missing(value):
        return None
    return str(value).replace("\x00", "").strip()


def canonicalize_text(value: Any) -> str | None:
    txt = clean_text(value)
    if txt is None:
        return None
    txt = txt.lower().replace("-", " ")
    txt = "".join(
        c for c in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(c)
    )
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt if txt else None


def normalize_token(value: Any, strip_lang_prefix: bool = True) -> str | None:
    txt = clean_text(value)
    if txt is None:
        return None
    txt = txt.lower()
    txt = txt.replace("*", " ")
    txt = txt.replace("•", " ")
    if strip_lang_prefix:
        txt = re.sub(r"^[a-z]{2,3}:", "", txt)
    txt = re.sub(r"\([^)]*\)", " ", txt)
    txt = re.sub(r"\d+(?:[.,]\d+)?\s*%?", " ", txt)
    txt = txt.replace("_", " ")
    txt = re.sub(r"[/+]", " ", txt)
    txt = re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ \-']", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip(" '\".,;:-")
    return canonicalize_text(txt)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def resolve_rules_path() -> str | None:
    env_path = os.getenv("NORMALIZATION_RULES_PATH")
    candidates = []
    if env_path:
        candidates.append(env_path)

    repo_root_candidate = Path(__file__).resolve().parents[2] / "config" / "normalization_rules.yml"
    candidates.extend(
        [
            "/opt/airflow/config/normalization_rules.yml",
            str(Path.cwd() / "config" / "normalization_rules.yml"),
            str(repo_root_candidate),
        ]
    )

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def normalize_rule_section(section: dict[str, Any]) -> dict[str, Any]:
    def list_to_canonical(items: Any) -> list[str]:
        if not isinstance(items, list):
            return []
        out = []
        for item in items:
            norm = canonicalize_text(item)
            if norm:
                out.append(norm)
        return out

    def map_to_canonical(mapping: Any) -> dict[str, str]:
        if not isinstance(mapping, dict):
            return {}
        out = {}
        for key, value in mapping.items():
            k = canonicalize_text(key)
            v = canonicalize_text(value)
            if k and v:
                out[k] = v
        return out

    return {
        "blacklist_exact": set(list_to_canonical(section.get("blacklist_exact"))),
        "blacklist_contains": list_to_canonical(section.get("blacklist_contains")),
        "remove_words": list_to_canonical(section.get("remove_words")),
        "corrections": map_to_canonical(section.get("corrections")),
        "standardization": map_to_canonical(section.get("standardization")),
    }


def load_normalization_rules() -> tuple[dict[str, Any], str]:
    rules = copy.deepcopy(DEFAULT_NORMALIZATION_RULES)
    source = "defaults"

    path = resolve_rules_path()
    if path and yaml is not None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            if isinstance(loaded, dict):
                rules = deep_merge(rules, loaded)
                source = path
        except Exception as exc:
            print(f"Warning: unable to read normalization rules from {path}: {exc}")
    elif path and yaml is None:
        print("Warning: PyYAML not installed, falling back to embedded normalization rules.")

    normalized_rules = {
        "ingredients": normalize_rule_section(rules.get("ingredients", {})),
        "categories": normalize_rule_section(rules.get("categories", {})),
    }
    return normalized_rules, source


def split_text_values(value: Any, separators: str = r"[,;]") -> list[str]:
    if is_missing(value):
        return []

    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]

    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return []
        if txt.startswith("[") and txt.endswith("]"):
            try:
                parsed = ast.literal_eval(txt)
                if isinstance(parsed, (list, tuple, set)):
                    return [str(v) for v in parsed]
            except (ValueError, SyntaxError):
                pass
        return [part.strip() for part in re.split(separators, txt)]

    return [str(value)]


def apply_rules_to_values(
    values: list[str],
    section_rules: dict[str, Any],
    stats: dict[str, int],
) -> list[str]:
    out = []
    seen = set()

    for raw in values:
        token = normalize_token(raw)
        if token is None:
            continue

        if token in section_rules["blacklist_exact"]:
            stats["rule_filtered"] += 1
            continue
        if any(flag in token for flag in section_rules["blacklist_contains"]):
            stats["rule_filtered"] += 1
            continue

        if section_rules["remove_words"]:
            before = token
            for word in section_rules["remove_words"]:
                token = re.sub(rf"\b{re.escape(word)}\b", " ", token)
            token = re.sub(r"\s+", " ", token).strip()
            if not token:
                stats["rule_filtered"] += 1
                continue
            if token != before:
                stats["rule_replacements"] += 1

        corrected = section_rules["corrections"].get(token)
        if corrected and corrected != token:
            token = corrected
            stats["rule_replacements"] += 1

        standardized = section_rules["standardization"].get(token)
        if standardized and standardized != token:
            token = standardized
            stats["rule_replacements"] += 1

        if len(token) < 2:
            stats["rule_filtered"] += 1
            continue

        if token not in seen:
            seen.add(token)
            out.append(token)

    return out


def normalize_categories_fields(
    product: dict[str, Any],
    rules: dict[str, Any],
    stats: dict[str, int],
) -> tuple[str | None, list[str]]:
    tag_values = normalize_tag_list(product.get("categories_tags"))
    normalized_tags = apply_rules_to_values(tag_values, rules["categories"], stats)

    if normalized_tags:
        categories_text = ", ".join(normalized_tags)
        raw_categories = clean_text(product.get("categories"))
        if categories_text != raw_categories:
            stats["categories_normalized"] += 1
        return categories_text, normalized_tags

    fallback_values = split_text_values(product.get("categories"), separators=r"[,;•]")
    normalized_fallback = apply_rules_to_values(fallback_values, rules["categories"], stats)
    if normalized_fallback:
        categories_text = ", ".join(normalized_fallback)
        raw_categories = clean_text(product.get("categories"))
        if categories_text != raw_categories:
            stats["categories_normalized"] += 1
        return categories_text, normalized_fallback

    return clean_text(product.get("categories")), []


def normalize_ingredients_text(
    product: dict[str, Any],
    rules: dict[str, Any],
    stats: dict[str, int],
) -> str | None:
    raw_ingredients = clean_text(product.get("ingredients_text")) or clean_text(product.get("ingredients_text_fr"))
    if raw_ingredients is None:
        return None

    values = split_text_values(raw_ingredients, separators=r"[,;•]")
    normalized = apply_rules_to_values(values, rules["ingredients"], stats)
    if normalized:
        normalized_text = ", ".join(normalized)
        if normalized_text != raw_ingredients:
            stats["ingredients_normalized"] += 1
        return normalized_text

    return raw_ingredients


def clean_float(value: Any) -> float | None:
    if is_missing(value):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def clean_int(value: Any) -> int | None:
    v = clean_float(value)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalize_code(value: Any) -> str | None:
    txt = clean_text(value)
    if txt is None:
        return None
    if txt.endswith(".0"):
        try:
            return str(int(float(txt)))
        except ValueError:
            return txt
    return txt


def normalize_nutrition_grade(value: Any) -> str | None:
    txt = clean_text(value)
    if txt is None:
        return None
    txt = txt.lower()
    if ":" in txt:
        txt = txt.split(":")[-1]
    match = re.search(r"[a-e]", txt)
    if not match:
        return None
    return match.group(0)


def score_to_grade(score: int | None) -> str | None:
    if score is None:
        return None
    if score <= -1:
        return "a"
    if score <= 2:
        return "b"
    if score <= 10:
        return "c"
    if score <= 18:
        return "d"
    return "e"


def normalize_tag(value: Any) -> str | None:
    txt = clean_text(value)
    if txt is None:
        return None
    if ":" in txt:
        txt = txt.split(":", 1)[1]
    txt = txt.strip().lower()
    return txt if txt else None


def split_values(value: Any) -> list[str]:
    if is_missing(value):
        return []

    raw_items = []
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    elif isinstance(value, str):
        txt = value.strip()
        if txt.startswith("[") and txt.endswith("]"):
            try:
                parsed = ast.literal_eval(txt)
                if isinstance(parsed, (list, tuple, set)):
                    raw_items = list(parsed)
                else:
                    raw_items = [txt]
            except (ValueError, SyntaxError):
                raw_items = [v.strip() for v in txt.split(",")]
        else:
            raw_items = [v.strip() for v in txt.split(",")]
    else:
        raw_items = [value]

    cleaned = []
    seen = set()
    for item in raw_items:
        txt = clean_text(item)
        if txt is None:
            continue
        if txt not in seen:
            seen.add(txt)
            cleaned.append(txt)
    return cleaned


def normalize_tag_list(value: Any) -> list[str]:
    out = []
    seen = set()
    for item in split_values(value):
        norm = normalize_tag(item)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def format_amount(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def normalize_quantity(value: Any) -> tuple[str | None, float | None, str | None]:
    txt = clean_text(value)
    if txt is None:
        return None, None, None

    chunks = re.split(r"[;,]", txt.lower())
    for raw in chunks:
        c = re.sub(r"\s+", "", raw)
        if not c:
            continue

        c = c.replace("×", "x")
        c = c.replace(",", ".")

        match_mult = re.match(r"^(\d+(?:\.\d+)?)[x](\d+(?:\.\d+)?)(kg|g|mg|oz|lb|ml|cl|dl|l)$", c)
        if match_mult:
            a, b, unit = match_mult.groups()
            quantity = float(a) * float(b)
        else:
            match_single = re.match(r"^(\d+(?:\.\d+)?)(kg|g|mg|oz|lb|ml|cl|dl|l)$", c)
            if not match_single:
                continue
            quantity, unit = match_single.groups()
            quantity = float(quantity)

        if unit == "kg":
            quantity *= 1000.0
            canonical_unit = "g"
        elif unit == "g":
            canonical_unit = "g"
        elif unit == "mg":
            quantity /= 1000.0
            canonical_unit = "g"
        elif unit == "oz":
            quantity *= 28.3495
            canonical_unit = "g"
        elif unit == "lb":
            quantity *= 453.592
            canonical_unit = "g"
        elif unit == "ml":
            quantity /= 1000.0
            canonical_unit = "l"
        elif unit == "cl":
            quantity /= 100.0
            canonical_unit = "l"
        elif unit == "dl":
            quantity /= 10.0
            canonical_unit = "l"
        else:
            canonical_unit = "l"

        quantity = round(quantity, 3)
        normalized_text = f"{format_amount(quantity)} {canonical_unit}"
        return normalized_text, quantity, canonical_unit

    return txt, None, None


def harmonize_energy(
    energy_100g: float | None,
    energy_kj_100g: float | None,
    energy_kcal_100g: float | None,
    stats: dict[str, int],
) -> tuple[float | None, float | None, float | None]:
    tolerance_kj = 2.0
    tolerance_kcal = 0.5

    if energy_kj_100g is None and energy_100g is not None:
        energy_kj_100g = energy_100g

    if energy_kcal_100g is not None:
        kj_calc = round(energy_kcal_100g * 4.184, 1)
        if energy_kj_100g is None:
            energy_kj_100g = kj_calc
            stats["energy_imputed"] += 1
        elif abs(energy_kj_100g - kj_calc) > tolerance_kj:
            energy_kj_100g = kj_calc
            stats["energy_corrected"] += 1
        if energy_100g is None or abs(energy_100g - energy_kj_100g) > tolerance_kj:
            energy_100g = energy_kj_100g
    elif energy_kj_100g is not None:
        kcal_calc = round(energy_kj_100g / 4.184, 1)
        if energy_kcal_100g is None:
            energy_kcal_100g = kcal_calc
            stats["energy_imputed"] += 1
        elif abs(energy_kcal_100g - kcal_calc) > tolerance_kcal:
            energy_kcal_100g = kcal_calc
            stats["energy_corrected"] += 1
        if energy_100g is None:
            energy_100g = energy_kj_100g

    return energy_100g, energy_kj_100g, energy_kcal_100g


def harmonize_salt_sodium(
    salt_100g: float | None,
    sodium_100g: float | None,
    stats: dict[str, int],
) -> tuple[float | None, float | None]:
    # In OFF, sodium_100g is typically in grams; relation: salt = sodium * 2.5
    tolerance = 0.05

    if salt_100g is not None and sodium_100g is None:
        sodium_100g = round(salt_100g / 2.5, 4)
        stats["sodium_imputed"] += 1
    elif sodium_100g is not None and salt_100g is None:
        salt_100g = round(sodium_100g * 2.5, 4)
        stats["salt_imputed"] += 1
    elif salt_100g is not None and sodium_100g is not None:
        sodium_expected = round(salt_100g / 2.5, 4)
        if abs(sodium_100g - sodium_expected) > tolerance:
            sodium_100g = sodium_expected
            stats["sodium_corrected"] += 1

    return salt_100g, sodium_100g


def completeness_score(row: dict[str, Any]) -> int:
    score = 0
    for key, value in row.items():
        if key == "code":
            continue
        if value_present(value):
            score += 1
    return score


def build_row(product: dict[str, Any], stats: dict[str, int], rules: dict[str, Any]) -> dict[str, Any]:
    nutriments = product.get("nutriments") or {}
    if not isinstance(nutriments, dict):
        nutriments = {}

    quantity_text, quantity_value, quantity_unit = normalize_quantity(product.get("quantity"))
    if quantity_value is not None and quantity_value <= 0:
        stats["quantity_invalid_nonpositive"] += 1
        quantity_value = None
        quantity_unit = None

    nutriscore_grade = normalize_nutrition_grade(product.get("nutriscore_grade"))
    nutriscore_score = clean_int(product.get("nutriscore_score"))
    if nutriscore_grade is None and nutriscore_score is not None:
        nutriscore_grade = score_to_grade(nutriscore_score)
        if nutriscore_grade is not None:
            stats["nutri_grade_imputed"] += 1
    if nutriscore_score is None and nutriscore_grade is not None:
        nutriscore_score = GRADE_TO_SCORE.get(nutriscore_grade)
        if nutriscore_score is not None:
            stats["nutri_score_imputed"] += 1

    energy_100g = clean_float(nutriments.get("energy_100g"))
    energy_kj_100g = clean_float(nutriments.get("energy-kj_100g"))
    energy_kcal_100g = clean_float(nutriments.get("energy-kcal_100g"))
    if energy_kcal_100g is None:
        energy_kcal_100g = clean_float(nutriments.get("energy_kcal_100g"))

    energy_100g, energy_kj_100g, energy_kcal_100g = harmonize_energy(
        energy_100g=energy_100g,
        energy_kj_100g=energy_kj_100g,
        energy_kcal_100g=energy_kcal_100g,
        stats=stats,
    )

    salt_100g, sodium_100g = harmonize_salt_sodium(
        salt_100g=clean_float(nutriments.get("salt_100g")),
        sodium_100g=clean_float(nutriments.get("sodium_100g")),
        stats=stats,
    )

    categories_text, categories_tags = normalize_categories_fields(product, rules, stats)
    ingredients_text = normalize_ingredients_text(product, rules, stats)

    return {
        "code": normalize_code(product.get("code")),
        "product_name": clean_text(product.get("product_name")) or clean_text(product.get("product_name_fr")),
        "brands": clean_text(product.get("brands")),
        "quantity": quantity_text,
        "quantity_value": quantity_value,
        "quantity_unit": quantity_unit,
        "url": clean_text(product.get("url")),
        "labels_tags": normalize_tag_list(product.get("labels_tags")),
        "categories": categories_text,
        "categories_tags": categories_tags,
        "nutriscore_grade": nutriscore_grade,
        "nutriscore_score": nutriscore_score,
        "nova_group": clean_int(product.get("nova_group")),
        "energy_100g": energy_100g,
        "energy_kj_100g": energy_kj_100g,
        "energy_kcal_100g": energy_kcal_100g,
        "fat_100g": clean_float(nutriments.get("fat_100g")),
        "saturated_fat_100g": clean_float(nutriments.get("saturated-fat_100g")),
        "carbohydrates_100g": clean_float(nutriments.get("carbohydrates_100g")),
        "sugars_100g": clean_float(nutriments.get("sugars_100g")),
        "fiber_100g": clean_float(nutriments.get("fiber_100g")),
        "proteins_100g": clean_float(nutriments.get("proteins_100g")),
        "salt_100g": salt_100g,
        "sodium_100g": sodium_100g,
        "ingredients_text": ingredients_text,
        "allergens_tags": normalize_tag_list(product.get("allergens_tags")),
        "traces_tags": normalize_tag_list(product.get("traces_tags")),
        "countries": clean_text(product.get("countries")),
        "countries_tags": normalize_tag_list(product.get("countries_tags")),
        "image_url": clean_text(product.get("image_url")),
        "image_small_url": clean_text(product.get("image_small_url")),
        "image_ingredients_url": clean_text(product.get("image_ingredients_url")),
        "image_ingredients_small_url": clean_text(product.get("image_ingredients_small_url")),
        "image_nutrition_url": clean_text(product.get("image_nutrition_url")),
    }


def parse_products(body: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    products = []
    stats = {"invalid_json_lines": 0, "empty_lines": 0}

    for line in body.splitlines():
        line = line.strip()
        if not line:
            stats["empty_lines"] += 1
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            stats["invalid_json_lines"] += 1
            continue
        if isinstance(obj, dict):
            products.append(obj)
        else:
            stats["invalid_json_lines"] += 1

    return products, stats


def transform_products(products: list[dict[str, Any]], rules: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    stats = {
        "rows_input": len(products),
        "duplicate_codes": 0,
        "duplicates_replaced": 0,
        "rows_without_code": 0,
        "energy_imputed": 0,
        "energy_corrected": 0,
        "salt_imputed": 0,
        "sodium_imputed": 0,
        "sodium_corrected": 0,
        "nutri_grade_imputed": 0,
        "nutri_score_imputed": 0,
        "quantity_invalid_nonpositive": 0,
        "categories_normalized": 0,
        "ingredients_normalized": 0,
        "rule_replacements": 0,
        "rule_filtered": 0,
    }

    dedup: dict[str, dict[str, Any]] = {}
    rows_without_code: list[dict[str, Any]] = []

    for product in products:
        row = build_row(product, stats=stats, rules=rules)
        code = row.get("code")
        if code is None:
            rows_without_code.append(row)
            stats["rows_without_code"] += 1
            continue

        existing = dedup.get(code)
        if existing is None:
            dedup[code] = row
            continue

        stats["duplicate_codes"] += 1
        if completeness_score(row) > completeness_score(existing):
            dedup[code] = row
            stats["duplicates_replaced"] += 1

    rows = list(dedup.values()) + rows_without_code
    df = pd.DataFrame(rows)
    df = df.reindex(columns=OUTPUT_COLUMNS)
    stats["rows_output"] = len(df)
    return df, stats


def run_transform(
    input_bucket: str,
    input_key: str,
    output_bucket: str,
    output_key: str,
) -> dict[str, int]:
    s3 = get_s3_client()
    rules, rules_source = load_normalization_rules()

    obj = s3.get_object(Bucket=input_bucket, Key=input_key)
    body = obj["Body"].read().decode("utf-8", errors="replace")

    products, parse_stats = parse_products(body)
    df, transform_stats = transform_products(products, rules=rules)
    stats = {**parse_stats, **transform_stats}
    stats["rules_loaded"] = 0 if rules_source == "defaults" else 1

    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)

    s3.put_object(Bucket=output_bucket, Key=output_key, Body=buf.getvalue())

    print(f"Transformed {len(df)} rows")
    print(f"Uploaded Parquet to s3://{output_bucket}/{output_key}")
    print(f"Normalization rules source: {rules_source}")
    print(
        "Quality summary: "
        f"input={stats['rows_input']}, output={stats['rows_output']}, "
        f"invalid_json={stats['invalid_json_lines']}, duplicate_codes={stats['duplicate_codes']}, "
        f"energy_imputed={stats['energy_imputed']}, energy_corrected={stats['energy_corrected']}, "
        f"salt_imputed={stats['salt_imputed']}, sodium_imputed={stats['sodium_imputed']}, "
        f"nutri_grade_imputed={stats['nutri_grade_imputed']}, nutri_score_imputed={stats['nutri_score_imputed']}, "
        f"quantity_invalid_nonpositive={stats['quantity_invalid_nonpositive']}, "
        f"categories_normalized={stats['categories_normalized']}, ingredients_normalized={stats['ingredients_normalized']}, "
        f"rule_replacements={stats['rule_replacements']}, rule_filtered={stats['rule_filtered']}"
    )
    return stats


def main():
    args = parse_args()
    run_transform(
        input_bucket=args.input_bucket,
        input_key=args.input_key,
        output_bucket=args.output_bucket,
        output_key=args.output_key,
    )


def transform_to_silver(
    input_key: str,
    output_key: str,
    input_bucket: str = None,
    output_bucket: str = None,
    **_,
):
    """
    Airflow callable (no argparse).
    Reads JSONL from MinIO (bronze) and writes Parquet to MinIO (silver).
    """
    if input_bucket is None:
        input_bucket = os.getenv("MINIO_BUCKET_BRONZE", "bronze")
    if output_bucket is None:
        output_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")

    return run_transform(
        input_bucket=input_bucket,
        input_key=input_key,
        output_bucket=output_bucket,
        output_key=output_key,
    )


if __name__ == "__main__":
    main()
