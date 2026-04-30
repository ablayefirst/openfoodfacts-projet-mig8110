#!/usr/bin/env python3
import argparse
import ast
import copy
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any
AI_CORRECTOR = None
AI_SYNONYM_MAP = None
PROCESS_FUNC = None
GET_CORRECTOR_FUNC = None
from sqlalchemy import create_engine

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.client import Config
try:
    import yaml
except ImportError:
    yaml = None


GRADE_TO_SCORE = {"a": -1, "b": 1, "c": 7, "d": 15, "e": 19}
GRADE_SCORE_RANGES = {
    "a": (None, -1),
    "b": (0, 2),
    "c": (3, 10),
    "d": (11, 18),
    "e": (19, None),
}
OFF_PRODUCT_BASE_URL = "https://world.openfoodfacts.org/product"
OFF_IMAGE_BASE_URL = "https://images.openfoodfacts.org/images/products"

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
    "category_primary_mapping": {
        "default": "autres",
        "ignore_contains": [],
        "rules": [],
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
    "categorie_principale",
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
    "ingredients_standardized",
    "ingredients_synonyms",     # CORRECTION : manquait dans OUTPUT_COLUMNS
    "allergens_tags",
    "traces_tags",
    "countries",
    "countries_tags",
    "image_url",
    "image_small_url",
    "image_ingredients_url",   # CORRECTION : manquait dans OUTPUT_COLUMNS
    "image_nutrition_url",
]

PARQUET_SCHEMA = pa.schema(
    [
        pa.field("code", pa.string()),
        pa.field("product_name", pa.string()),
        pa.field("brands", pa.string()),
        pa.field("quantity", pa.string()),
        pa.field("quantity_value", pa.float64()),
        pa.field("quantity_unit", pa.string()),
        pa.field("url", pa.string()),
        pa.field("labels_tags", pa.list_(pa.string())),
        pa.field("categories", pa.string()),
        pa.field("categories_tags", pa.list_(pa.string())),
        pa.field("categorie_principale", pa.string()),
        pa.field("nutriscore_grade", pa.string()),
        pa.field("nutriscore_score", pa.int64()),
        pa.field("nova_group", pa.int64()),
        pa.field("energy_100g", pa.float64()),
        pa.field("energy_kj_100g", pa.float64()),
        pa.field("energy_kcal_100g", pa.float64()),
        pa.field("fat_100g", pa.float64()),
        pa.field("saturated_fat_100g", pa.float64()),
        pa.field("carbohydrates_100g", pa.float64()),
        pa.field("sugars_100g", pa.float64()),
        pa.field("fiber_100g", pa.float64()),
        pa.field("proteins_100g", pa.float64()),
        pa.field("salt_100g", pa.float64()),
        pa.field("sodium_100g", pa.float64()),
        pa.field("ingredients_text", pa.string()),
        pa.field("ingredients_standardized", pa.string()),  # CORRECTION : manquait dans PARQUET_SCHEMA
        pa.field("ingredients_synonyms", pa.string()),     # CORRECTION : manquait dans PARQUET_SCHEMA
        pa.field("allergens_tags", pa.list_(pa.string())),
        pa.field("traces_tags", pa.list_(pa.string())),
        pa.field("countries", pa.string()),
        pa.field("countries_tags", pa.list_(pa.string())),
        pa.field("image_url", pa.string()),
        pa.field("image_small_url", pa.string()),
        pa.field("image_ingredients_url", pa.string()),     # CORRECTION : manquait dans PARQUET_SCHEMA
        pa.field("image_nutrition_url", pa.string()),
    ]
)



def init_ai(engine):
    """
    Initialise le pipeline AI (embedding + LLM) de manière lazy.
    Corrections :
      [C-1] imports groupés dans le même bloc conditionnel
      [C-2] PROCESS_FUNC pointe vers process() avec la bonne signature (3 args)
      [C-3] EmbeddingCorrector et db_loader importés dans le même if
    """
    global AI_CORRECTOR, AI_SYNONYM_MAP, PROCESS_FUNC

    # Imports lazy — évite de charger sentence_transformers au démarrage Airflow
    if PROCESS_FUNC is None:
        from scripts.ingredients_ai.processor import process
        PROCESS_FUNC = process

    if AI_CORRECTOR is None:
        from scripts.ingredients_ai.embedding import EmbeddingCorrector
        from scripts.ingredients_ai.db_loader import load_synonyms_from_db

        reference_map  = load_synonyms_from_db(engine)
        AI_SYNONYM_MAP = reference_map
        AI_CORRECTOR   = EmbeddingCorrector(list(reference_map.keys()))
        print(f"[AI] Corrector initialisé avec {len(reference_map)} ingrédients bruts")

    return AI_CORRECTOR, AI_SYNONYM_MAP
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


def normalize_token(
    value: Any,
    strip_lang_prefix: bool = True,
    keep_parentheses: bool = False
) -> str | None:

    txt = clean_text(value)
    if txt is None:
        return None

    txt = txt.lower()
    txt = txt.replace("*", " ")
    txt = txt.replace("•", " ")

    if strip_lang_prefix:
        txt = re.sub(r"^[a-z]{2,3}:", "", txt)

    # 🔥 FIX ICI
    if not keep_parentheses:
        txt = re.sub(r"\([^)]*\)", " ", txt)

    txt = re.sub(r"\d+(?:[.,]\d+)?\s*%?", " ", txt)
    txt = txt.replace("_", " ")
    txt = re.sub(r"[/+]", " ", txt)

    txt = re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ \-()']", " ", txt)

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


def normalize_primary_category_rules(section: dict[str, Any]) -> dict[str, Any]:
    def list_to_canonical(items: Any) -> list[str]:
        if not isinstance(items, list):
            return []
        out = []
        for item in items:
            norm = canonicalize_text(item)
            if norm:
                out.append(norm)
        return out

    default_value = clean_text(section.get("default")) if isinstance(section, dict) else None
    default_value = default_value or "autres"
    ignore_contains = list_to_canonical(section.get("ignore_contains")) if isinstance(section, dict) else []

    raw_rules = section.get("rules") if isinstance(section, dict) else None
    normalized_rules: list[dict[str, Any]] = []
    if isinstance(raw_rules, list):
        for rule in raw_rules:
            if not isinstance(rule, dict):
                continue
            name = clean_text(rule.get("name"))
            if not name:
                continue
            keywords_raw = rule.get("keywords")
            if not isinstance(keywords_raw, list):
                continue
            keywords = []
            seen = set()
            for keyword in keywords_raw:
                norm = canonicalize_text(keyword)
                if norm and norm not in seen:
                    seen.add(norm)
                    keywords.append(norm)
            if keywords:
                normalized_rules.append({"name": name, "keywords": keywords})

    return {"default": default_value, "ignore_contains": ignore_contains, "rules": normalized_rules}


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
        "category_primary_mapping": normalize_primary_category_rules(
            rules.get("category_primary_mapping", {})
        ),
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
    is_ingredient: bool = False
) -> list[str]:

    out = []
    seen = set()

    for raw in values:

        # 🔥 FIX ICI
        token = normalize_token(raw, keep_parentheses=is_ingredient)

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
    recovery_mode: bool = False,
) -> tuple[str | None, list[str]]:
    tag_values = normalize_tag_list(product.get("categories_tags"))
    normalized_tags = apply_rules_to_values(tag_values, rules["categories"], stats)

    if normalized_tags:
        categories_text = ", ".join(normalized_tags)
        raw_categories = clean_text(product.get("categories"))
        if categories_text != raw_categories:
            stats["categories_normalized"] += 1
        return categories_text, normalized_tags

    fallback_sources = [product.get("categories")]
    if recovery_mode:
        fallback_sources.extend(
            [
                product.get("categories_en"),
                product.get("categories_fr"),
                product.get("pnns_groups_1"),
                product.get("pnns_groups_2"),
            ]
        )

    for source in fallback_sources:
        fallback_values = split_text_values(source, separators=r"[,;•]")
        normalized_fallback = apply_rules_to_values(fallback_values, rules["categories"], stats)
        if normalized_fallback:
            categories_text = ", ".join(normalized_fallback)
            raw_categories = clean_text(source)
            if categories_text != raw_categories:
                stats["categories_normalized"] += 1
            return categories_text, normalized_fallback

    return clean_text(product.get("categories")), []


def classify_primary_category(
    categories_tags: list[str],
    categories_text: str | None,
    rules: dict[str, Any],
    stats: dict[str, int],
) -> tuple[str, str]:
    mapping = rules.get("category_primary_mapping", {})
    mapping_rules = mapping.get("rules", [])
    ignore_contains = mapping.get("ignore_contains", [])
    default_value = mapping.get("default") or "autres"

    def sanitize_candidate(value: Any) -> str | None:
        candidate = canonicalize_text(value)
        if not candidate:
            return None

        cleaned = candidate
        for phrase in ignore_contains:
            if phrase:
                cleaned = cleaned.replace(phrase, " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return None
        return cleaned

    def score_from_candidates(candidates: list[str]) -> tuple[str | None, int]:
        best_name = None
        best_score = 0
        best_index = None

        for idx, rule in enumerate(mapping_rules):
            rule_name = rule.get("name")
            keywords = rule.get("keywords", [])
            if not rule_name or not keywords:
                continue

            score = 0
            for candidate in candidates:
                for keyword in keywords:
                    if candidate == keyword:
                        score += 3
                    elif re.search(rf"\b{re.escape(keyword)}\b", candidate):
                        score += 2
                    # Substring fallback is useful for long tokens only; short tokens create noise.
                    elif len(keyword) >= 4 and keyword in candidate:
                        score += 1

            if score > best_score:
                best_name = rule_name
                best_score = score
                best_index = idx
            elif score == best_score and score > 0 and best_index is not None and idx < best_index:
                best_name = rule_name
                best_index = idx

        return best_name, best_score

    tag_candidates = []
    for tag in categories_tags:
        candidate = sanitize_candidate(tag)
        if candidate:
            tag_candidates.append(candidate)
    matched, matched_score = score_from_candidates(tag_candidates)
    if matched and matched_score > 0:
        stats["primary_category_assigned"] += 1
        stats["primary_category_from_tags"] += 1
        return matched, "categories_tags"

    fallback_candidates = []
    for category_value in split_text_values(categories_text, separators=r"[,;|]"):
        candidate = sanitize_candidate(category_value)
        if candidate:
            fallback_candidates.append(candidate)
    matched, matched_score = score_from_candidates(fallback_candidates)
    if matched and matched_score > 0:
        stats["primary_category_assigned"] += 1
        stats["primary_category_from_categories"] += 1
        return matched, "categories"

    stats["primary_category_default"] += 1
    return default_value, "default"


def normalize_ingredients_text(
    product: dict[str, Any],
    rules: dict[str, Any],
    stats: dict[str, int],
    recovery_mode: bool = False,
) -> str | None:
    ingredient_keys = [
        "ingredients_text",
        "ingredients_text_fr",
        "ingredients_text_en",
        "ingredients_text_with_allergens",
        "ingredients_text_with_allergens_fr",
        "ingredients_text_with_allergens_en",
    ]
    for key in sorted(product):
        if not key.startswith("ingredients_text_"):
            continue
        if key.endswith("_debug") or key in ingredient_keys:
            continue
        ingredient_keys.append(key)

    if recovery_mode:
        for key in ("ingredients_debug", "ingredients_original_tags"):
            if key in product and key not in ingredient_keys:
                ingredient_keys.append(key)

    raw_ingredients = first_clean_text(*(product.get(key) for key in ingredient_keys))
    if raw_ingredients is None:
        return None

    values = split_text_values(raw_ingredients, separators=r"[,;•/]")
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


def first_clean_text(*values: Any) -> str | None:
    for value in values:
        txt = clean_text(value)
        if txt is not None:
            return txt
    return None


def build_product_url(code: str | None, raw_url: Any = None) -> str | None:
    direct_url = first_clean_text(raw_url)
    if direct_url is not None:
        return direct_url
    if code is None:
        return None
    return f"{OFF_PRODUCT_BASE_URL}/{code}"


def normalize_brands(product: dict[str, Any], recovery_mode: bool = False) -> str | None:
    direct_brand = first_clean_text(
        product.get("brands"),
        product.get("brand_owner"),
        product.get("brand_owner_imported"),
    )
    if recovery_mode and direct_brand is None:
        direct_brand = first_clean_text(
            product.get("brands_en"),
            product.get("brands_fr"),
        )
    if direct_brand is not None:
        return direct_brand

    brand_tags = normalize_tag_list(product.get("brands_tags"))
    if not brand_tags:
        return None

    formatted = []
    for tag in brand_tags:
        pretty = tag.replace("-", " ").strip()
        if pretty:
            formatted.append(pretty)
    if not formatted:
        return None
    return ", ".join(formatted)


def barcode_to_off_path(code: str | None) -> str | None:
    if code is None:
        return None

    digits = re.sub(r"\D", "", code)
    if not digits:
        return None

    parts = []
    while len(digits) > 4:
        parts.append(digits[:3])
        digits = digits[3:]
    parts.append(digits)
    return "/".join(parts)


def preferred_image_languages(product: dict[str, Any]) -> list[str]:
    candidates = [
        clean_text(product.get("lang")),
        clean_text(product.get("lc")),
        "en",
        "fr",
    ]

    preferred = []
    seen = set()
    for candidate in candidates:
        if candidate is None:
            continue
        lang = candidate.strip().lower()
        if lang and lang not in seen:
            seen.add(lang)
            preferred.append(lang)
    return preferred


def resolve_image_entry(
    images: dict[str, Any],
    image_type: str,
    preferred_langs: list[str],
) -> tuple[str | None, dict[str, Any] | None]:
    selected = images.get("selected")
    if isinstance(selected, dict):
        selected_group = selected.get(image_type)
        if isinstance(selected_group, dict):
            for lang in preferred_langs:
                candidate = selected_group.get(lang)
                if isinstance(candidate, dict):
                    return f"{image_type}_{lang}", candidate
            for lang, candidate in selected_group.items():
                if isinstance(candidate, dict):
                    return f"{image_type}_{lang}", candidate

    for lang in preferred_langs:
        candidate_key = f"{image_type}_{lang}"
        candidate = images.get(candidate_key)
        if isinstance(candidate, dict):
            return candidate_key, candidate

    fallback = images.get(image_type)
    if isinstance(fallback, dict):
        return image_type, fallback

    for key, candidate in images.items():
        if key.startswith(f"{image_type}_") and isinstance(candidate, dict):
            return key, candidate

    return None, None


def build_image_from_images(
    code: str | None,
    product: dict[str, Any],
    image_type: str,
    size: str,
) -> str | None:
    images = product.get("images")
    if not isinstance(images, dict):
        return None

    barcode_path = barcode_to_off_path(code)
    if barcode_path is None:
        return None

    key, image_entry = resolve_image_entry(images, image_type, preferred_image_languages(product))
    if key is None or not isinstance(image_entry, dict):
        return None

    rev = clean_text(image_entry.get("rev"))
    if rev is None:
        return None

    return f"{OFF_IMAGE_BASE_URL}/{barcode_path}/{key}.{rev}.{size}.jpg"


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


def score_matches_grade(grade: str | None, score: int | None) -> bool:
    if grade is None or score is None:
        return False

    lower, upper = GRADE_SCORE_RANGES.get(grade, (None, None))
    if lower is not None and score < lower:
        return False
    if upper is not None and score > upper:
        return False
    return True


def pick_product_name(product: dict[str, Any], recovery_mode: bool = False) -> str | None:
    candidates = [
        product.get("product_name"),
        product.get("product_name_fr"),
    ]
    if recovery_mode:
        candidates.extend(
            [
                product.get("product_name_en"),
                product.get("generic_name"),
                product.get("generic_name_fr"),
                product.get("generic_name_en"),
                product.get("abbreviated_product_name"),
            ]
        )
    return first_clean_text(*candidates)


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


def convert_measurement(quantity: float, unit: str) -> tuple[float, str] | None:
    if unit == "kg":
        return quantity * 1000.0, "g"
    if unit == "g":
        return quantity, "g"
    if unit == "mg":
        return quantity / 1000.0, "g"
    if unit == "oz":
        return quantity * 28.3495, "g"
    if unit == "lb":
        return quantity * 453.592, "g"
    if unit == "ml":
        return quantity / 1000.0, "l"
    if unit == "cl":
        return quantity / 100.0, "l"
    if unit == "dl":
        return quantity / 10.0, "l"
    if unit == "l":
        return quantity, "l"
    if unit == "floz":
        return quantity * 0.0295735, "l"
    return None


def normalize_quantity_text(txt: str) -> str:
    txt = txt.lower().strip()
    txt = txt.replace("×", " x ")
    txt = txt.replace(",", ".")
    txt = re.sub(r"\bnet\s*(?:wt|weight)?\.?\b", " ", txt)
    txt = re.sub(r"\bapprox\.?\b", " ", txt)
    txt = re.sub(r"(\d)\s*litres?\b", r"\1 l", txt)
    txt = re.sub(r"(\d)\s*liters?\b", r"\1 l", txt)
    txt = re.sub(r"\blitres?\b", " l ", txt)
    txt = re.sub(r"\bliters?\b", " l ", txt)
    txt = re.sub(r"\blitre\b", " l ", txt)
    txt = re.sub(r"\bliter\b", " l ", txt)
    txt = re.sub(r"(\d)\s*gm\b", r"\1 g", txt)
    txt = re.sub(r"(\d)\s*gr\b", r"\1 g", txt)
    txt = re.sub(r"\bgrams?\b", " g ", txt)
    txt = re.sub(r"\bgms\b", " g ", txt)
    txt = re.sub(r"\bgm\b", " g ", txt)
    txt = re.sub(r"\bgr\b", " g ", txt)
    txt = re.sub(r"\bpieces?\b", " unit ", txt)
    txt = re.sub(r"\bpcs\b", " unit ", txt)
    txt = re.sub(r"\bpc\b", " unit ", txt)
    txt = re.sub(r"\btablets?\b", " unit ", txt)
    txt = re.sub(r"\btablillas?\b", " unit ", txt)
    txt = re.sub(r"\bcapsules?\b", " unit ", txt)
    txt = re.sub(r"\bcaplets?\b", " unit ", txt)
    txt = re.sub(r"\blbs\b", " lb ", txt)
    txt = re.sub(r"\bfl\.?\s*oz\b", " floz ", txt)
    txt = re.sub(r"\bozs\b", " oz ", txt)
    txt = re.sub(r"/\s*(bottle|pack|box|bag|jar|tray|can|carton|wrapper|sachet)\b", "", txt)
    txt = re.sub(r"\bper\s+(bottle|pack|box|bag|jar|tray|can|carton|wrapper|sachet)\b", "", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def normalize_quantity(value: Any) -> tuple[str | None, float | None, str | None]:
    txt = clean_text(value)
    if txt is None:
        return None, None, None

    normalized = normalize_quantity_text(txt)
    chunks = re.split(r"[;,]", normalized)
    metric_units = {"kg", "g", "mg", "ml", "cl", "dl", "l"}
    count_units = {"unit"}
    candidates: list[tuple[int, float, str]] = []

    for raw in chunks:
        if not raw.strip():
            continue

        multiplier_matches = re.finditer(
            r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(kg|g|mg|oz|lb|ml|cl|dl|l|floz|unit)\b",
            raw,
        )
        for match in multiplier_matches:
            a, b, unit = match.groups()
            if unit in count_units:
                quantity = float(a) * float(b)
                canonical_unit = unit
                priority = 2
            else:
                converted = convert_measurement(float(a) * float(b), unit)
                if converted is None:
                    continue
                quantity, canonical_unit = converted
                priority = 0 if unit in metric_units else 1
            candidates.append((priority, quantity, canonical_unit))

        single_matches = re.finditer(
            r"(\d+(?:\.\d+)?)\s*(kg|g|mg|oz|lb|ml|cl|dl|l|floz|unit)\b",
            raw,
        )
        for match in single_matches:
            quantity_raw, unit = match.groups()
            if unit in count_units:
                quantity = float(quantity_raw)
                canonical_unit = unit
                priority = 2
            else:
                converted = convert_measurement(float(quantity_raw), unit)
                if converted is None:
                    continue
                quantity, canonical_unit = converted
                priority = 0 if unit in metric_units else 1
            candidates.append((priority, quantity, canonical_unit))

        bare_number_match = re.fullmatch(r"(\d+(?:\.\d+)?)", raw.strip())
        if bare_number_match:
            quantity = float(bare_number_match.group(1))
            candidates.append((2, quantity, "unit"))

    if candidates:
        priority, quantity, canonical_unit = min(candidates, key=lambda item: (item[0], item[1] <= 0, item[1]))
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
        if key in {"code", "last_modified_t"}:
            continue
        if value_present(value):
            score += 1
    return score


def should_replace_duplicate(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    existing_ts = clean_int(existing.get("last_modified_t"))
    candidate_ts = clean_int(candidate.get("last_modified_t"))
    if existing_ts is not None and candidate_ts is not None:
        return candidate_ts >= existing_ts
    return completeness_score(candidate) >= completeness_score(existing)


def build_row(
    product: dict[str, Any],
    stats: dict[str, int],
    rules: dict[str, Any],
    recovery_mode: bool = False,
) -> dict[str, Any]:

    nutriments = product.get("nutriments") or {}
    if not isinstance(nutriments, dict):
        nutriments = {}

    code = normalize_code(product.get("code"))

    quantity_text, quantity_value, quantity_unit = normalize_quantity(product.get("quantity"))
    if quantity_value is not None and quantity_value <= 0:
        stats["quantity_invalid_nonpositive"] += 1
        quantity_value = None
        quantity_unit = None

    nutriscore_grade = normalize_nutrition_grade(product.get("nutriscore_grade"))
    nutriscore_score = clean_int(product.get("nutriscore_score"))

    energy_100g = clean_float(nutriments.get("energy_100g"))
    energy_kj_100g = clean_float(nutriments.get("energy-kj_100g"))
    energy_kcal_100g = clean_float(nutriments.get("energy-kcal_100g"))

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

    categories_text, categories_tags = normalize_categories_fields(
        product,
        rules,
        stats,
        recovery_mode=recovery_mode,
    )

    categorie_principale, _ = classify_primary_category(
        categories_tags,
        categories_text,
        rules,
        stats
    )

    # =========================
    # 🔥 AI INJECTION (UPDATED)
    # =========================
    raw_ingredients = normalize_ingredients_text(
        product,
        rules,
        stats,
        recovery_mode=recovery_mode,
    )

    ingredients_text = raw_ingredients
    ingredients_standardized = raw_ingredients
    ingredients_synonyms = None

    def is_valid_ingredients(text):
        if not text or not isinstance(text, str):
            return False
        text = text.strip()
        if not text:
            return False
        cleaned = text.replace(",", "").replace("(", "").replace(")", "").strip()
        return bool(cleaned)

    if (
        is_valid_ingredients(raw_ingredients)
        and AI_CORRECTOR is not None
        and AI_SYNONYM_MAP is not None
        and PROCESS_FUNC is not None
    ):
        try:
            # [C-1] Bonne signature : process(text, corrector, synonym_map)
            ai_result = PROCESS_FUNC(
                raw_ingredients,
                AI_CORRECTOR,
                AI_SYNONYM_MAP,
            )

            if isinstance(ai_result, dict):
                ai_text        = ai_result.get("ingredients_text", [])
                ai_standardized = ai_result.get("ingredients_standardized", [])
                ai_synonyms    = ai_result.get("ingredients_synonyms", [])

                if isinstance(ai_text, list) and ai_text:
                    ingredients_text = ", ".join(ai_text)

                if isinstance(ai_standardized, list) and ai_standardized:
                    ingredients_standardized = " , ".join(ai_standardized)
                else:
                    ingredients_standardized = ingredients_text

                # [C-2] Séparateur " ; " pour éviter conflit avec virgule dans les noms
                # [C-3] Pas de double appel LLM — si synonymes vides, fallback sur standardized
                if isinstance(ai_synonyms, list):

                    cleaned_synonyms = []
                    for s in ai_synonyms:
                        if s and str(s).strip():
                            val = str(s).strip()
                            val = val.replace(";", "|").replace(",", "|").replace("/", "|")
                            parts = [p.strip() for p in val.split("|") if p.strip()]
                            # remove duplicates
                            val_clean = "|".join(dict.fromkeys(parts))
                            cleaned_synonyms.append(val_clean)
                    if cleaned_synonyms:
                        # 🔥 FORMAT CORRECT pour load_to_postgres
                        # Séparateur " , " entre ingrédients, "|" entre synonymes d'un même ingrédient
                        # [FIX] Séparateur ", " requis par load_to_postgres._parse_synonyms_string
                        ingredients_synonyms = ", ".join(cleaned_synonyms)
                    else:
                        # 🔥 fallback si tout est vide
                        ingredients_synonyms = ingredients_standardized or raw_ingredients

                else:
                    # 🔥 fallback total
                    if ingredients_standardized:
                        ingredients_synonyms = ingredients_standardized
                    else:
                        ingredients_synonyms = raw_ingredients

                stats["ingredients_ai_used"] = stats.get("ingredients_ai_used", 0) + 1


        except Exception as e:
            print(f"[AI] ❌ {code} — {type(e).__name__}: {e}")
            ingredients_text         = raw_ingredients
            ingredients_standardized = raw_ingredients
            ingredients_synonyms     = None
    else:
        # AI non disponible ou ingrédients invalides → valeurs brutes conservées
        ingredients_synonyms = None
    # =========================

    image_url = first_clean_text(
        product.get("image_url"),
        product.get("image_front_url"),
        build_image_from_images(code, product, "front", "400"),
    )

    image_small_url = first_clean_text(
        product.get("image_small_url"),
        product.get("image_front_small_url"),
        build_image_from_images(code, product, "front", "100"),
    )

    image_nutrition_url = first_clean_text(
        product.get("image_nutrition_url"),
        build_image_from_images(code, product, "nutrition", "400"),
    )

    # [C-3] image_ingredients_url était dans OUTPUT_COLUMNS/PARQUET_SCHEMA
    # mais absent du calcul et du return → colonne toujours NULL
    image_ingredients_url = first_clean_text(
        product.get("image_ingredients_url"),
        build_image_from_images(code, product, "ingredients", "400"),
    )

    return {
        "code": code,
        "last_modified_t": clean_int(product.get("last_modified_t")),
        "product_name": pick_product_name(product, recovery_mode=recovery_mode),
        "brands": normalize_brands(product, recovery_mode=recovery_mode),
        "quantity": quantity_text,
        "quantity_value": quantity_value,
        "quantity_unit": quantity_unit,
        "url": build_product_url(code, product.get("url")),
        "labels_tags": normalize_tag_list(product.get("labels_tags")),
        "categories": categories_text,
        "categories_tags": categories_tags,
        "categorie_principale": categorie_principale,
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

        # 🔥 NOUVEAUX CHAMPS
        "ingredients_text": ingredients_text,
        "ingredients_standardized": ingredients_standardized,
        "ingredients_synonyms": ingredients_synonyms,
        "allergens_tags": normalize_tag_list(product.get("allergens_tags")),
        "traces_tags": normalize_tag_list(product.get("traces_tags")),
        "countries": clean_text(product.get("countries")),
        "countries_tags": normalize_tag_list(product.get("countries_tags")),
        "image_url": image_url,
        "image_small_url": image_small_url,
        "image_ingredients_url": image_ingredients_url,
        "image_nutrition_url": image_nutrition_url,
    }


def quantity_is_final(row: dict[str, Any]) -> bool:
    quantity = clean_text(row.get("quantity"))
    if quantity is None:
        return True
    return clean_float(row.get("quantity_value")) is not None and clean_text(row.get("quantity_unit")) is not None


def nutriscore_is_final(row: dict[str, Any]) -> bool:
    grade = normalize_nutrition_grade(row.get("nutriscore_grade"))
    score = clean_int(row.get("nutriscore_score"))
    if grade is None and score is None:
        return True
    if grade is None or score is None:
        return False
    return score_matches_grade(grade, score)


def energy_is_final(row: dict[str, Any]) -> bool:
    energy = clean_float(row.get("energy_100g"))
    energy_kj = clean_float(row.get("energy_kj_100g"))
    energy_kcal = clean_float(row.get("energy_kcal_100g"))
    if energy is None and energy_kj is None and energy_kcal is None:
        return True
    norm_energy, norm_kj, norm_kcal = harmonize_energy(
        energy,
        energy_kj,
        energy_kcal,
        stats={"energy_imputed": 0, "energy_corrected": 0},
    )
    return energy == norm_energy and energy_kj == norm_kj and energy_kcal == norm_kcal


def salt_sodium_is_final(row: dict[str, Any]) -> bool:
    salt = clean_float(row.get("salt_100g"))
    sodium = clean_float(row.get("sodium_100g"))
    if salt is None and sodium is None:
        return True
    norm_salt, norm_sodium = harmonize_salt_sodium(
        salt,
        sodium,
        stats={"salt_imputed": 0, "sodium_imputed": 0, "sodium_corrected": 0},
    )
    return salt == norm_salt and sodium == norm_sodium


def evaluate_final_contract(row: dict[str, Any]) -> list[str]:
    issues = []

    if normalize_code(row.get("code")) is None:
        issues.append("missing_code")
    if clean_text(row.get("product_name")) is None:
        issues.append("missing_product_name")
    if clean_text(row.get("categories")) is None:
        issues.append("missing_categories")
    if clean_text(row.get("categorie_principale")) is None:
        issues.append("missing_categorie_principale")
    if not quantity_is_final(row):
        issues.append("quantity_not_standardized")
    if not nutriscore_is_final(row):
        issues.append("nutriscore_inconsistent")
    if not energy_is_final(row):
        issues.append("energy_inconsistent")
    if not salt_sodium_is_final(row):
        issues.append("salt_sodium_inconsistent")

    return issues


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


def init_transform_stats() -> dict[str, int]:
    return {
        "rows_input": 0,
        "rows_output": 0,
        "duplicate_codes": 0,
        "ingredients_ai_used": 0,
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
        "primary_category_assigned": 0,
        "primary_category_from_tags": 0,
        "primary_category_from_categories": 0,
        "primary_category_default": 0,
        "rule_replacements": 0,
        "rule_filtered": 0,
    }


def init_parse_stats() -> dict[str, int]:
    return {"invalid_json_lines": 0, "empty_lines": 0}


def transform_products(products: list[dict[str, Any]], rules: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    stats = init_transform_stats()
    stats["rows_input"] = len(products)

    dedup: dict[str, dict[str, Any]] = {}
    rows_without_code: list[dict[str, Any]] = []

    for product in products:
        row = build_row(product, stats=stats, rules=rules, recovery_mode=True)
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
        if should_replace_duplicate(existing, row):
            dedup[code] = row
            stats["duplicates_replaced"] += 1

    rows = list(dedup.values()) + rows_without_code
    df = pd.DataFrame(rows)
    df = df.reindex(columns=OUTPUT_COLUMNS)
    stats["rows_output"] = len(df)
    return df, stats


def dataframe_to_table(df: pd.DataFrame) -> pa.Table:
    df = df.reindex(columns=OUTPUT_COLUMNS)
    return pa.Table.from_pandas(df, schema=PARQUET_SCHEMA, preserve_index=False)


def write_empty_parquet(parquet_path: str) -> None:
    empty_table = pa.Table.from_arrays(
        [pa.array([], type=field.type) for field in PARQUET_SCHEMA],
        schema=PARQUET_SCHEMA,
    )
    pq.write_table(empty_table, parquet_path)


def write_rows_chunk(writer: pq.ParquetWriter | None, rows: list[dict[str, Any]], parquet_path: str) -> pq.ParquetWriter:
    if not rows:
        return writer

    df = pd.DataFrame(rows)
    table = dataframe_to_table(df)
    if writer is None:
        writer = pq.ParquetWriter(parquet_path, PARQUET_SCHEMA, compression="snappy")
    writer.write_table(table)
    return writer


def iter_json_lines(streaming_body, max_retries=3):
    for attempt in range(max_retries):
        try:
            print(f"[STREAM] Reading stream (attempt {attempt+1})")
            for raw_line in streaming_body.iter_lines():
                if raw_line is None:
                    continue
                yield raw_line.decode("utf-8", errors="replace")
            return  # ✅ succès → on sort proprement
        except Exception as e:
            print(f"[STREAM ERROR] attempt {attempt+1}: {e}")
        
    print("[STREAM ERROR] Max retries reached — stream aborted")


def stream_transform_to_parquet(
    body_stream,
    rules: dict[str, Any],
    parquet_path: str,
    chunk_size: int = 5000,
) -> dict[str, int]:

    parse_stats = init_parse_stats()
    transform_stats = init_transform_stats()

    # 🔥 AJOUT ICI (important)
    transform_stats["ingredients_ai_used"] = transform_stats.get("ingredients_ai_used", 0)

    seen_codes: set[str] = set()
    rows_batch: list[dict[str, Any]] = []
    writer: pq.ParquetWriter | None = None

    try:
        print("[STREAM] Start processing JSONL stream")
        for raw_line in iter_json_lines(body_stream):
            line = raw_line.strip()
            if not line:
                parse_stats["empty_lines"] += 1
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                parse_stats["invalid_json_lines"] += 1
                continue

            if not isinstance(obj, dict):
                parse_stats["invalid_json_lines"] += 1
                continue

            transform_stats["rows_input"] += 1

            row = build_row(obj, stats=transform_stats, rules=rules, recovery_mode=True)

            code = row.get("code")
            if code is None:
                transform_stats["rows_without_code"] += 1
            elif code in seen_codes:
                transform_stats["duplicate_codes"] += 1
                transform_stats["duplicates_replaced"] += 1
            else:
                seen_codes.add(code)

            rows_batch.append({column: row.get(column) for column in OUTPUT_COLUMNS})

            if len(rows_batch) >= chunk_size:
                writer = write_rows_chunk(writer, rows_batch, parquet_path)
                transform_stats["rows_output"] += len(rows_batch)
                rows_batch = []

        if rows_batch:
            writer = write_rows_chunk(writer, rows_batch, parquet_path)
            transform_stats["rows_output"] += len(rows_batch)

    finally:
        if writer is not None:
            writer.close()

    if writer is None:
        write_empty_parquet(parquet_path)

    # =========================
    # 🔥 AJOUT LOGS AI (ICI)
    # =========================
    ai_used = transform_stats.get("ingredients_ai_used", 0)
    total = transform_stats.get("rows_output", 0)

    print(f"AI usage: {ai_used}")

    if total > 0:
        ratio = ai_used / total
        print(f"AI usage ratio: {ratio:.2%}")

    # =========================

    return {**parse_stats, **transform_stats}


def run_transform(
    input_bucket: str,
    input_key: str,
    output_bucket: str,
    output_key: str,
) -> dict[str, int]:
    s3 = get_s3_client()
    rules, rules_source = load_normalization_rules()
    # 🔥 ICI EXACTEMENT
    engine = create_engine(
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
)

    init_ai(engine)
    obj = s3.get_object(Bucket=input_bucket, Key=input_key)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_file:
        parquet_path = tmp_file.name

    try:
        stats = stream_transform_to_parquet(obj["Body"], rules=rules, parquet_path=parquet_path)
        stats["rules_loaded"] = 0 if rules_source == "defaults" else 1

        s3.upload_file(parquet_path, output_bucket, output_key)

        print(f"Transformed {stats['rows_output']} rows")
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
            f"primary_category_assigned={stats['primary_category_assigned']}, "
            f"primary_category_from_tags={stats['primary_category_from_tags']}, "
            f"primary_category_from_categories={stats['primary_category_from_categories']}, "
            f"primary_category_default={stats['primary_category_default']}, "
            f"rule_replacements={stats['rule_replacements']}, rule_filtered={stats['rule_filtered']}"
        )
        return stats
    finally:
        if os.path.exists(parquet_path):
            os.remove(parquet_path)


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