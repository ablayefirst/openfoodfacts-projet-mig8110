#!/usr/bin/env python3
"""Generate canonical ingredient synonyms with an optional LLM pass.

This script intentionally runs before similarity generation. It enriches the
existing `ingredient` / `synonyme_ingredient` tables without changing product
links directly. Downstream similarity can resolve raw ingredient names through
`synonyme_ingredient`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import psycopg2


DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_CACHE_PATH = Path(os.getenv("AIRFLOW_HOME", "/opt/airflow")) / "data" / "cache_ingredient_synonyms.json"
DEFAULT_FETCH_MULTIPLIER = 20
CACHE_SCHEMA_VERSION = "english_canonical_strict_v1"

NOISE_WORDS = {
    "allergen",
    "allergens",
    "allergene",
    "allergenes",
    "barcode",
    "beverage",
    "calories",
    "calorie",
    "carbohydrate",
    "carbohydrates",
    "cholesterol",
    "distributed",
    "distributor",
    "facility",
    "facts",
    "glucides",
    "information",
    "ingredients",
    "nutrition",
    "nutritional",
    "packaged",
    "prepared",
    "protein",
    "proteines",
    "serving",
    "store",
    "total",
    "www",
}

AMBIGUOUS_ADDITIVES = {
    "bha",
    "bht",
}

RELATION_TYPES = {
    "exact",
    "traduction",
    "correction",
    "variante",
}

GENERIC_PHRASES = {
    "bio engineered food",
    "bioengineered food",
    "contains",
    "contains less than",
    "may contain",
}

ALLOWED_SHORT_INGREDIENTS = {
    "ail",
    "ble",
    "cod",
    "eau",
    "egg",
    "ham",
    "jus",
    "oat",
    "oil",
    "pea",
    "riz",
    "rum",
    "rye",
    "sel",
    "soy",
    "tea",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate ingredient canonical names and synonyms with an LLM."
    )
    parser.add_argument("--limit", type=int, default=100, help="Maximum ingredients to process.")
    parser.add_argument("--batch-size", type=int, default=20, help="Ingredients per LLM call.")
    parser.add_argument("--max-candidate-words", type=int, default=6, help="Reject candidates with too many words.")
    parser.add_argument("--max-candidate-length", type=int, default=80, help="Reject candidates longer than this.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model name.")
    parser.add_argument("--cache-path", default=str(DEFAULT_CACHE_PATH), help="JSON cache path.")
    parser.add_argument("--dry-run", action="store_true", help="Call/cache LLM results but do not write DB rows.")
    parser.add_argument("--preview-only", action="store_true", help="Only list candidates. No LLM call, no writes.")
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Include ingredients that already have at least one synonym.",
    )
    parser.add_argument(
        "--max-llm-calls",
        type=int,
        default=None,
        help="Optional hard limit for LLM calls during this run.",
    )
    return parser.parse_args()


def get_pg_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "openfood_db"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres123"),
    )


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).replace("\x00", " ").strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" ,.;:|/\\")
    return value


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def clean_synonym(value: str | None) -> str:
    value = normalize_text(value)
    if not value:
        return ""
    if value in {"unknown", "none", "null", "n/a", "ingredient", "ingredients"}:
        return ""
    if len(value) > 120:
        return ""
    return value


def is_candidate_for_llm(
    value: str | None,
    *,
    max_words: int = 6,
    max_length: int = 80,
) -> bool:
    value = normalize_text(value)
    if not value:
        return False

    if value in AMBIGUOUS_ADDITIVES:
        return False

    if len(value) > max_length:
        return False

    words = re.findall(r"[a-zàâçéèêëîïôûùüÿñæœ]+", value)
    if not words:
        return False

    if len(value) <= 3 and value not in ALLOWED_SHORT_INGREDIENTS:
        return False

    if len(words) == 1 and len(words[0]) <= 3 and words[0] not in ALLOWED_SHORT_INGREDIENTS:
        return False

    if len(words) > 1 and words[0] in {"a", "an", "and", "or"}:
        return False

    if len(words) > 1 and len(words[0]) <= 2:
        return False

    if len(words) > max_words:
        return False

    if any(len(word) > 32 for word in words):
        return False

    if re.search(r"\d", value):
        return False

    if value in GENERIC_PHRASES:
        return False

    if any(phrase in value for phrase in GENERIC_PHRASES):
        return False

    word_set = set(words)
    if word_set & NOISE_WORDS:
        return False

    # Reject strings that look like broken OCR/token soup more than ingredients.
    avg_word_len = sum(len(word) for word in words) / len(words)
    if len(words) >= 4 and avg_word_len < 3.0:
        return False

    return True


def load_cache(path: str) -> dict[str, dict[str, Any]]:
    cache_path = Path(path)
    if not cache_path.exists():
        return {}
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {}
        if data.get("__schema_version") != CACHE_SCHEMA_VERSION:
            return {}
        return {
            key: value
            for key, value in data.items()
            if key != "__schema_version" and isinstance(value, dict)
        }
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(path: str, cache: dict[str, dict[str, Any]]) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"__schema_version": CACHE_SCHEMA_VERSION, **cache}
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)


def fetch_candidates(conn, limit: int, include_existing: bool) -> list[tuple[int, str]]:
    with conn.cursor() as cur:
        where_extra = ""
        if not include_existing:
            where_extra = """
              AND NOT EXISTS (
                  SELECT 1
                  FROM synonyme_ingredient s
                  WHERE s.id_ingredient = i.id_ingredient
              )
            """
        cur.execute(
            f"""
            SELECT i.id_ingredient, i.ingredients_nom
            FROM ingredient i
            WHERE i.ingredients_nom IS NOT NULL
              AND TRIM(i.ingredients_nom) <> ''
              {where_extra}
            ORDER BY LENGTH(TRIM(i.ingredients_nom)), i.ingredients_nom
            LIMIT %s
            """,
            (limit,),
        )
        return [(int(row[0]), str(row[1])) for row in cur.fetchall()]


def filter_candidates(
    candidates: list[tuple[int, str]],
    *,
    limit: int,
    max_words: int,
    max_length: int,
) -> tuple[list[tuple[int, str]], int]:
    filtered = []
    rejected = 0
    seen = set()

    for ingredient_id, name in candidates:
        normalized = normalize_text(name)
        if normalized in seen:
            rejected += 1
            continue
        if not is_candidate_for_llm(
            normalized,
            max_words=max_words,
            max_length=max_length,
        ):
            rejected += 1
            continue
        seen.add(normalized)
        filtered.append((ingredient_id, normalized))
        if len(filtered) >= limit:
            break

    return filtered, rejected


def chunked(items: list[tuple[int, str]], size: int):
    size = max(1, int(size))
    for start in range(0, len(items), size):
        yield items[start:start + size]


def build_prompt(ingredients: list[str]) -> str:
    return f"""
Tu es un moteur strict de normalisation d'ingrédients alimentaires.

Pour chaque ingrédient en entrée:
- conserve un seul ingrédient canonique court en anglais américain;
- si l'ingrédient original est français, espagnol, portugais ou une autre langue,
  traduis seulement le canonique en anglais;
- ajoute 1 à 5 variantes utiles si disponibles;
- ne mélange pas plusieurs ingrédients;
- ne devine pas une famille trop large si l'ingrédient est précis;
- garde les synonymes utiles dans leur langue originale ou en anglais;
- privilégie les traductions directes et les corrections orthographiques;
- n'ajoute pas de produits dérivés, parties, préparations ou sous-types
  comme synonymes si l'entrée ne les mentionne pas explicitement;
- exemples à éviter:
  - farine/flour n'est pas une traduction de wheat;
  - egg white ou egg yolk ne sont pas synonymes de egg;
  - prosciutto ou serrano ne sont pas synonymes de ham;
  - olive oil ou vegetable oil ne sont pas synonymes de oil;
- classe chaque lien avec relation_type:
  - exact: même forme normalisée;
  - traduction: même ingrédient dans une autre langue;
  - correction: faute, accent, orthographe corrigée;
  - variante: forme proche mais pas strictement identique (frais, sec, entier, huile d'olive -> huile);
- retourne uniquement du JSON valide.

Exemples de canonique attendu:
- ail -> garlic
- alho -> garlic
- agua -> water
- eau -> water
- haricot -> bean
- bean -> bean
- oeuf -> egg

Format attendu:
{{
  "ingredients": [
    {{
      "ingredient": "valeur originale",
      "canonical": "nom canonique",
      "canonical_relation": "exact|traduction|correction|variante",
      "synonyms": [
        {{"value": "synonyme 1", "relation_type": "traduction|correction|variante"}},
        {{"value": "synonyme 2", "relation_type": "traduction|correction|variante"}}
      ],
      "language": "fr|en|unknown",
      "confidence": 0.0
    }}
  ]
}}

Ingrédients:
{json.dumps(ingredients, ensure_ascii=False)}
""".strip()


def extract_json_object(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def call_llm(batch: list[tuple[int, str]], model: str) -> list[dict[str, Any]]:
    from openai import OpenAI

    ingredients = [name for _, name in batch]
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": build_prompt(ingredients)}],
    )
    content = response.choices[0].message.content
    payload = extract_json_object(content)
    rows = payload.get("ingredients", [])
    return rows if isinstance(rows, list) else []


def normalize_relation_type(value: str | None, synonym: str, canonical: str) -> str:
    relation_type = normalize_text(value)
    if relation_type in RELATION_TYPES:
        return relation_type

    synonym_norm = normalize_text(synonym)
    canonical_norm = normalize_text(canonical)
    if synonym_norm == canonical_norm:
        return "exact"
    if synonym_norm.replace("œ", "oe") == canonical_norm.replace("œ", "oe"):
        return "correction"
    if strip_accents(synonym_norm).replace("œ", "oe") == strip_accents(canonical_norm).replace("œ", "oe"):
        return "correction"
    return "variante"


def iter_synonym_candidates(row: dict[str, Any], raw_norm: str):
    canonical_relation = row.get("canonical_relation")
    yield raw_norm, canonical_relation

    raw_synonyms = row.get("synonyms") or []
    for item in raw_synonyms:
        if isinstance(item, dict):
            yield item.get("value") or item.get("synonym"), item.get("relation_type")
        else:
            yield item, None


def normalize_llm_rows(batch: list[tuple[int, str]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_input = {
        normalize_text(row.get("ingredient")): row
        for row in rows
        if isinstance(row, dict)
    }
    normalized = []
    for ingredient_id, raw_name in batch:
        raw_norm = normalize_text(raw_name)
        row = by_input.get(raw_norm, {})
        canonical = clean_synonym(row.get("canonical")) or raw_norm
        language = clean_synonym(row.get("language")) or None
        try:
            confidence = float(row.get("confidence", 0.70))
        except (TypeError, ValueError):
            confidence = 0.70
        confidence = max(0.0, min(1.0, confidence))

        synonyms = []
        for candidate, relation_type in iter_synonym_candidates(row, raw_norm):
            synonym = clean_synonym(candidate)
            if not synonym or synonym == canonical:
                continue
            normalized_relation = normalize_relation_type(relation_type, synonym, canonical)
            synonym_row = {
                "value": synonym,
                "relation_type": normalized_relation,
            }
            if synonym_row not in synonyms:
                synonyms.append(synonym_row)

        normalized.append(
            {
                "source_id": ingredient_id,
                "raw_name": raw_norm,
                "canonical": canonical,
                "synonyms": synonyms[:6],
                "language": language,
                "confidence": confidence,
            }
        )
    return normalized


def upsert_ingredient(cur, name: str) -> int:
    cur.execute(
        """
        INSERT INTO ingredient (ingredients_nom)
        VALUES (%s)
        ON CONFLICT (ingredients_nom) DO NOTHING
        RETURNING id_ingredient
        """,
        (name,),
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute("SELECT id_ingredient FROM ingredient WHERE ingredients_nom = %s", (name,))
    return int(cur.fetchone()[0])


def upsert_synonym(
    cur,
    synonym: str,
    ingredient_id: int,
    language: str | None,
    confidence: float,
    relation_type: str,
) -> None:
    cur.execute(
        """
        SELECT id_synonyme
        FROM synonyme_ingredient
        WHERE LOWER(TRIM(nom_synonyme)) = LOWER(TRIM(%s))
        LIMIT 1
        """,
        (synonym,),
    )
    existing = cur.fetchone()
    if existing:
        cur.execute(
            """
            UPDATE synonyme_ingredient
            SET id_ingredient = %s,
                langue = COALESCE(%s, langue),
                source = 'llm',
                relation_type = %s,
                confidence = GREATEST(COALESCE(confidence, 0), %s)
            WHERE id_synonyme = %s
            """,
            (ingredient_id, language, relation_type, confidence, existing[0]),
        )
        return

    cur.execute(
        """
        INSERT INTO synonyme_ingredient (
            nom_synonyme,
            id_ingredient,
            langue,
            source,
            relation_type,
            confidence
        )
        VALUES (%s, %s, %s, 'llm', %s, %s)
        """,
        (synonym, ingredient_id, language, relation_type, confidence),
    )


def persist_rows(conn, rows: list[dict[str, Any]]) -> tuple[int, int]:
    canonical_count = 0
    synonym_count = 0
    with conn.cursor() as cur:
        for row in rows:
            canonical_id = upsert_ingredient(cur, row["canonical"])
            canonical_count += 1
            for synonym in row["synonyms"]:
                if isinstance(synonym, dict):
                    synonym_value = synonym["value"]
                    relation_type = synonym.get("relation_type", "variante")
                else:
                    synonym_value = synonym
                    relation_type = normalize_relation_type(None, synonym_value, row["canonical"])
                upsert_synonym(
                    cur,
                    synonym_value,
                    canonical_id,
                    row["language"],
                    row["confidence"],
                    relation_type,
                )
                synonym_count += 1
    conn.commit()
    return canonical_count, synonym_count


def generate_ingredient_synonyms(
    *,
    limit: int = 100,
    batch_size: int = 20,
    model: str = DEFAULT_MODEL,
    cache_path: str = str(DEFAULT_CACHE_PATH),
    dry_run: bool = False,
    preview_only: bool = False,
    include_existing: bool = False,
    max_llm_calls: int | None = None,
    max_candidate_words: int = 6,
    max_candidate_length: int = 80,
) -> dict[str, int]:
    conn = get_pg_connection()
    try:
        raw_limit = max(limit, limit * DEFAULT_FETCH_MULTIPLIER)
        raw_candidates = fetch_candidates(conn, raw_limit, include_existing)
        candidates, rejected_candidates = filter_candidates(
            raw_candidates,
            limit=limit,
            max_words=max_candidate_words,
            max_length=max_candidate_length,
        )
        print(f"Ingrédients lus: {len(raw_candidates)}")
        print(f"Ingrédients rejetés par filtre: {rejected_candidates}")
        print(f"Ingrédients candidats propres: {len(candidates)}")
        if preview_only:
            for _, name in candidates[:50]:
                print(f"- {name}")
            return {
                "raw_candidates": len(raw_candidates),
                "rejected_candidates": rejected_candidates,
                "candidates": len(candidates),
                "llm_calls": 0,
                "synonyms_written": 0,
            }

        cache = load_cache(cache_path)
        llm_calls = 0
        canonical_written = 0
        synonyms_written = 0

        for batch in chunked(candidates, batch_size):
            uncached = [
                item for item in batch
                if normalize_text(item[1]) not in cache
            ]

            if uncached:
                if max_llm_calls is not None and llm_calls >= max_llm_calls:
                    print("Limite max LLM atteinte, arrêt.")
                    break
                llm_rows = call_llm(uncached, model)
                normalized_rows = normalize_llm_rows(uncached, llm_rows)
                for row in normalized_rows:
                    cache[row["raw_name"]] = row
                llm_calls += 1
                save_cache(cache_path, cache)

            rows = [
                cache[normalize_text(name)]
                for _, name in batch
                if normalize_text(name) in cache
            ]

            if dry_run:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
                continue

            canon_count, syn_count = persist_rows(conn, rows)
            canonical_written += canon_count
            synonyms_written += syn_count
            print(f"Batch écrit: {canon_count} canoniques, {syn_count} synonymes")

        save_cache(cache_path, cache)
        return {
            "raw_candidates": len(raw_candidates),
            "rejected_candidates": rejected_candidates,
            "candidates": len(candidates),
            "llm_calls": llm_calls,
            "canonical_written": canonical_written,
            "synonyms_written": synonyms_written,
        }
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    stats = generate_ingredient_synonyms(
        limit=args.limit,
        batch_size=args.batch_size,
        model=args.model,
        cache_path=args.cache_path,
        dry_run=args.dry_run,
        preview_only=args.preview_only,
        include_existing=args.include_existing,
        max_llm_calls=args.max_llm_calls,
        max_candidate_words=args.max_candidate_words,
        max_candidate_length=args.max_candidate_length,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
