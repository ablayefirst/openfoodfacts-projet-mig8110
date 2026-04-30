#!/usr/bin/env python3
"""
Load Silver Parquet from MinIO into PostgreSQL normalized schema (Gold).

Adapté au schéma v3 :
  - produit         : id_produit SERIAL + code_barre UNIQUE + nom_produit
  - marque          : nom_marque
  - categorie       : nom_categorie
  - trace           : nom_trace
  - contient        : remplace produit_ingredient_similaire
  - sous_ingredient : hiérarchie multi-niveaux sans récursion
  - trace_allergene : trace → allergene
  - ingredient_standardise : id_ingredient

Corrections v4 :
  [FIX-1] Alignement ingredient_standardise : suppression du brut_to_canonical
          qui croisait items hiérarchique avec items_std plat → DB corrompue.
          Remplacé par std_index_for_niveau1 : compteur dédié aux items niveau 1.
  [FIX-2] insert_synonyms : normalisation lower/strip, dédoublonnage, skip canonique.
  [FIX-3] upsert_ingredient_standardise : COALESCE + RETURNING.
  [FIX-4] DELETE ciblé (purge ordres disparus uniquement).
  [FIX-5] parse_ingredients_hierarchiques : profondeur arbitraire.
"""

import argparse
import ast
import os
import re
import time
import traceback
from pathlib import Path
import tempfile

import boto3
import pandas as pd
import psycopg2
import pyarrow.parquet as pq
from botocore.client import Config


# ══════════════════════════════════════════════════════════════════
# MONITORING HELPERS
# ══════════════════════════════════════════════════════════════════

_C = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "red":     "\033[31m",
    "cyan":    "\033[36m",
    "blue":    "\033[34m",
    "magenta": "\033[35m",
    "white":   "\033[97m",
}

def _c(color: str, text: str) -> str:
    if os.getenv("NO_COLOR"):
        return text
    return f"{_C.get(color, '')}{text}{_C['reset']}"

def mon_header(title: str, width: int = 64) -> None:
    bar = "═" * width
    print(f"\n{_c('cyan', bar)}")
    print(_c("bold", f"  {title}"))
    print(_c("cyan", bar))

def mon_section(title: str, width: int = 60) -> None:
    bar = "─" * width
    print(f"\n{_c('blue', bar)}")
    print(_c("bold", f"  {title}"))
    print(_c("blue", bar))

def mon_step(icon: str, label: str, detail: str = "", color: str = "white") -> None:
    detail_str = f" {_c('dim', '→')} {_c('dim', detail)}" if detail else ""
    print(f"    {icon}  {_c(color, label)}{detail_str}")

def mon_ok(label: str, detail: str = "") -> None:
    mon_step(_c("green", "✔"), label, detail, color="white")

def mon_warn(label: str, detail: str = "") -> None:
    mon_step(_c("yellow", "⚠"), label, detail, color="yellow")

def mon_err(label: str, detail: str = "") -> None:
    mon_step(_c("red", "✘"), label, detail, color="red")

def mon_info(label: str, detail: str = "") -> None:
    mon_step(_c("cyan", "ℹ"), label, detail, color="white")

def mon_skip(label: str, detail: str = "") -> None:
    mon_step(_c("dim", "↷"), label, detail, color="dim")

def mon_table(rows: list, indent: int = 4) -> None:
    if not rows:
        return
    max_key = max(len(str(k)) for k, _ in rows)
    pad = " " * indent
    for k, v in rows:
        k_str = str(k).ljust(max_key)
        v_col = "yellow" if v == 0 else "white"
        print(f"{pad}{_c('dim', k_str)}  {_c(v_col, str(v))}")

def mon_progress_bar(current: int, total: int, width: int = 30) -> str:
    if total == 0:
        return "[" + "─" * width + "] ?%"
    pct  = current / total
    done = int(pct * width)
    bar  = "█" * done + "░" * (width - done)
    return f"[{_c('green', bar)}] {pct * 100:.1f}%"

def mon_timer(elapsed: float) -> str:
    if elapsed < 60:
        return f"{elapsed:.2f}s"
    m, s = divmod(int(elapsed), 60)
    return f"{m}m{s:02d}s"

def mon_separator(char: str = "·", width: int = 60) -> None:
    print(_c("dim", char * width))

def mon_produit_header(code: str, nom: str, idx) -> None:
    label = f"{code}  {_c('dim', '|')}  {nom[:40]}"
    print(f"\n  {_c('magenta', '▶')} {_c('bold', label)}  {_c('dim', f'(idx={idx})')}")

def mon_produit_footer(code: str, action: str, cat: int, ingr: int, sous: int, tr: int, al: int) -> None:
    action_col = "green" if action in ("INSERT", "UPDATE") else "yellow"
    print(
        f"  {_c('dim', '└──')} "
        f"{_c(action_col, action)}  "
        f"cat={_c('cyan', str(cat))}  "
        f"ingr={_c('cyan', str(ingr))}+{_c('dim', str(sous))}  "
        f"traces={_c('cyan', str(tr))}  "
        f"allergènes={_c('cyan', str(al))}"
    )

def mon_cache_summary(caches: dict) -> None:
    mon_section("Caches en mémoire")
    rows = [
        ("marques",    len(caches["marque"])),
        ("catégories", len(caches["categorie"])),
        ("ingr. std",  len(caches["ingredient_std"])),
        ("traces",     len(caches["trace"])),
        ("allergènes", len(caches["allergene"])),
    ]
    mon_table(rows)

def mon_batch_summary(batch_index, rows_in_batch, batch_skipped, elapsed, batch_stats):
    loaded = rows_in_batch - batch_skipped
    mon_section(f"Résumé Batch #{batch_index}")
    print(
        f"    {mon_progress_bar(loaded, rows_in_batch)}  "
        f"{_c('green', str(loaded))}/{rows_in_batch} chargées  "
        f"{_c('red', str(batch_skipped))} ignorées  "
        f"({_c('cyan', mon_timer(elapsed))})"
    )
    print()
    warnings = [
        ("marque NULL",          batch_stats["marque_null"]),
        ("catégories NULL",      batch_stats["cat_null"]),
        ("ingredients NULL",     batch_stats["ingr_text_null"]),
        ("ingredients std NULL", batch_stats["ingr_std_null"]),
        ("traces NULL",          batch_stats["traces_null"]),
        ("allergènes NULL",      batch_stats["allergens_null"]),
        ("total champs vides",   batch_stats["fields_warn_total"]),
    ]
    for label, val in warnings:
        if val > 0:
            mon_warn(label, str(val))


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    p.add_argument("--input-key", required=True)
    p.add_argument("--schema-sql", default=None)
    return p.parse_args()


# ══════════════════════════════════════════════════════════════════
# Clients
# ══════════════════════════════════════════════════════════════════
def get_s3_client():
    endpoint   = os.environ["MINIO_ENDPOINT"].strip()
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    secure     = os.getenv("MINIO_SECURE", "false").lower() == "true"
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        endpoint_url = endpoint
    else:
        scheme       = "https" if secure else "http"
        endpoint_url = f"{scheme}://{endpoint}"
    mon_section("Connexion MinIO")
    mon_info("Endpoint",   endpoint_url)
    mon_info("Secure",     str(secure))
    mon_info("Access key", f"{access_key[:4]}***")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    mon_ok("Client S3 initialisé")
    return client


def get_pg_connection():
    host     = os.getenv("POSTGRES_HOST", "postgres")
    port     = os.getenv("POSTGRES_PORT", "5432")
    dbname   = os.getenv("POSTGRES_DB", "openfood_db")
    user     = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres123")
    mon_section("Connexion PostgreSQL")
    mon_info("Hôte", f"{host}:{port}")
    mon_info("Base", dbname)
    mon_info("User", user)
    conn = psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password
    )
    conn.autocommit = False
    mon_ok("Connexion établie")
    return conn


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════
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

def clean_optional_text(value):
    txt = clean_text(value)
    return None if txt in {"None", "null"} else txt

def clean_optional_bigint(value):
    txt = clean_optional_text(value)
    if txt is None:
        return None
    try:
        return int(txt)
    except (TypeError, ValueError):
        return None

def normalize_nutrition_grade(value):
    txt = clean_text(value)
    if txt is None:
        return None
    txt = txt.strip().lower()
    if ":" in txt:
        txt = txt.split(":")[-1]
    match = re.search(r"[a-e]", txt)
    return match.group(0) if match else None

def normalize_tag(value):
    txt = clean_text(value)
    if txt is None:
        return None
    txt = txt.strip()
    if ":" in txt:
        txt = txt.split(":", 1)[1]
    txt = txt.strip().lower()
    return txt if txt else None

def get_categories_value(row):
    val = row.get("categories_tags")
    if val is not None and not isinstance(val, str):
        try:
            if len(val) > 0:
                return val
        except TypeError:
            pass
    if not is_missing(val):
        return val
    return row.get("categories")

def split_values(value) -> list:
    if is_missing(value):
        return []
    raw_items = []
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    elif hasattr(value, "tolist") and not isinstance(value, str):
        converted = value.tolist()
        raw_items = list(converted) if isinstance(converted, (list, tuple, set)) else [converted]
    elif isinstance(value, str):
        txt = value.strip()
        if not txt:
            return []
        if txt.startswith("[") and txt.endswith("]"):
            try:
                parsed = ast.literal_eval(txt)
                raw_items = list(parsed) if isinstance(parsed, (list, tuple, set)) else [txt]
            except (SyntaxError, ValueError):
                raw_items = [p.strip() for p in txt.split(",")]
        else:
            raw_items = [p.strip() for p in txt.split(",")]
    else:
        raw_items = [value]
    seen, cleaned = set(), []
    for item in raw_items:
        txt = clean_text(item)
        if txt and txt not in seen:
            seen.add(txt)
            cleaned.append(txt)
    return cleaned

def safe_col(row, col):
    return row.get(col) if col in row.index else None

def derive_quantity_text(row):
    quantity = clean_text(row.get("quantity"))
    if quantity:
        return quantity
    value = clean_float(row.get("quantity_value"))
    unit  = clean_text(row.get("quantity_unit"))
    if value is None or unit is None:
        return None
    return f"{value:g} {unit}"

def parse_ingredients_hierarchiques(raw: str) -> list:
    """
    Parse ingredients_text en liste hiérarchique.
    Retourne [{"nom": str, "ordre": int, "niveau": int}, ...]

    [FIX-5] Gère la profondeur arbitraire :
      niveau monte de 1 à chaque "(" | descend à chaque ")" | jamais sous 1
    Exemple : "A (B (C, D), E)" → A niv1 | B niv2 | C niv3 | D niv3 | E niv2
    """
    if not raw or not raw.strip():
        return []
    if "(" not in raw:
        items = split_values(raw)
        return [{"nom": n, "ordre": i + 1, "niveau": 1} for i, n in enumerate(items)]
    result = []
    ordre  = [0]
    niveau = [1]
    def push(token: str) -> None:
        nom = clean_text(token.strip().rstrip(",").strip())
        if nom:
            ordre[0] += 1
            result.append({"nom": nom, "ordre": ordre[0], "niveau": niveau[0]})
    token = ""
    for ch in raw:
        if ch == "(":
            push(token); token = ""; niveau[0] += 1
        elif ch == ")":
            push(token); token = ""; niveau[0] = max(1, niveau[0] - 1)
        elif ch == ",":
            push(token); token = ""
        else:
            token += ch
    push(token)
    return result


# ══════════════════════════════════════════════════════════════════
# Schema
# ══════════════════════════════════════════════════════════════════
def resolve_default_schema_path() -> str:
    here      = Path(__file__).resolve()
    dags_root = here.parents[1]
    return str(dags_root / "sql" / "create_tables.sql")

def ensure_schema(cur, schema_sql_path=None):
    path = schema_sql_path or resolve_default_schema_path()
    path = str(Path(path).resolve())
    mon_section("Application du schéma SQL")
    mon_info("Fichier", path)
    if not os.path.exists(path):
        mon_err("Fichier introuvable", path)
        raise FileNotFoundError(f"Schema SQL file not found at: {path}")
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    cur.execute(sql)
    mon_ok("Schéma appliqué avec succès")


# ══════════════════════════════════════════════════════════════════
# DB helpers
# ══════════════════════════════════════════════════════════════════

def get_or_create(cur, table: str, id_col: str, value_col: str, value: str) -> int:
    cur.execute(
        f"INSERT INTO {table} ({value_col}) VALUES (%s) ON CONFLICT ({value_col}) DO NOTHING",
        (value,),
    )
    cur.execute(f"SELECT {id_col} FROM {table} WHERE {value_col} = %s", (value,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"[get_or_create] {table}.{id_col} introuvable pour {value!r}")
    return row[0]


# ── 1. marque ─────────────────────────────────────────────────────
def upsert_marque(cur, nom: str, cache: dict):
    if not nom:
        return None
    if nom not in cache:
        cache[nom] = get_or_create(cur, "marque", "id_marque", "nom_marque", nom)
    return cache[nom]


# ── 2. produit ────────────────────────────────────────────────────
def upsert_produit(cur, row, id_marque) -> int:
    categories           = split_values(get_categories_value(row))
    categorie_principale = normalize_tag(categories[0]) if categories else None
    code_barre           = clean_text(row.get("code"))
    nom_produit          = clean_text(row.get("product_name"))
    cur.execute(
        """
        INSERT INTO produit (
            code_barre, nom_produit, quantite, categorie_principale,
            nutrition_grade, nutriscore_score, nova_group,
            energy_kcal_100g,
            fat_100g, saturated_fat_100g, carbohydrates_100g,
            sugars_100g, fiber_100g, proteins_100g, salt_100g,
            image_url, image_small_url, image_ingredients_url, image_nutrition_url,
            id_marque
        )
        VALUES (
            %(code_barre)s, %(nom_produit)s, %(quantite)s, %(cat_princ)s,
            %(ng)s, %(ns)s, %(nova)s,
            %(energy)s,
            %(fat)s, %(sat_fat)s, %(carbs)s,
            %(sugars)s, %(fiber)s, %(proteins)s, %(salt)s,
            %(img)s, %(img_sm)s, %(img_ing)s, %(img_nut)s,
            %(id_marque)s
        )
        ON CONFLICT (code_barre) DO UPDATE SET
            nom_produit           = EXCLUDED.nom_produit,
            quantite              = EXCLUDED.quantite,
            categorie_principale  = EXCLUDED.categorie_principale,
            nutrition_grade       = EXCLUDED.nutrition_grade,
            nutriscore_score      = EXCLUDED.nutriscore_score,
            nova_group            = EXCLUDED.nova_group,
            energy_kcal_100g      = EXCLUDED.energy_kcal_100g,
            fat_100g              = EXCLUDED.fat_100g,
            saturated_fat_100g    = EXCLUDED.saturated_fat_100g,
            carbohydrates_100g    = EXCLUDED.carbohydrates_100g,
            sugars_100g           = EXCLUDED.sugars_100g,
            fiber_100g            = EXCLUDED.fiber_100g,
            proteins_100g         = EXCLUDED.proteins_100g,
            salt_100g             = EXCLUDED.salt_100g,
            image_url             = EXCLUDED.image_url,
            image_small_url       = EXCLUDED.image_small_url,
            image_ingredients_url = EXCLUDED.image_ingredients_url,
            image_nutrition_url   = EXCLUDED.image_nutrition_url,
            id_marque             = EXCLUDED.id_marque
        RETURNING id_produit
        """,
        {
            "code_barre":  code_barre,
            "nom_produit": nom_produit,
            "quantite":    derive_quantity_text(row),
            "cat_princ":   categorie_principale,
            "ng":          normalize_nutrition_grade(row.get("nutriscore_grade")),
            "ns":          clean_int(row.get("nutriscore_score")),
            "nova":        clean_int(row.get("nova_group")),
            "energy":      clean_float(safe_col(row, "energy_kcal_100g")),
            "fat":         clean_float(row.get("fat_100g")),
            "sat_fat":     clean_float(row.get("saturated_fat_100g")),
            "carbs":       clean_float(row.get("carbohydrates_100g")),
            "sugars":      clean_float(row.get("sugars_100g")),
            "fiber":       clean_float(row.get("fiber_100g")),
            "proteins":    clean_float(safe_col(row, "proteins_100g")),
            "salt":        clean_float(row.get("salt_100g")),
            "img":         clean_text(row.get("image_url")),
            "img_sm":      clean_text(row.get("image_small_url")),
            "img_ing":     clean_text(safe_col(row, "image_ingredients_url")),
            "img_nut":     clean_text(row.get("image_nutrition_url")),
            "id_marque":   id_marque,
        },
    )
    result = cur.fetchone()
    if result:
        return result[0]
    cur.execute("SELECT id_produit FROM produit WHERE code_barre = %s", (code_barre,))
    return cur.fetchone()[0]


# ── 3. produit_categorie ──────────────────────────────────────────
def load_categories(cur, id_produit: int, row, cache: dict) -> int:
    categories = split_values(get_categories_value(row))
    count = 0
    for niveau, raw_cat in enumerate(categories, start=1):
        nom = normalize_tag(raw_cat) or clean_text(raw_cat)
        if not nom:
            continue
        if nom not in cache:
            cache[nom] = get_or_create(cur, "categorie", "id_categorie", "nom_categorie", nom)
        cur.execute(
            """
            INSERT INTO produit_categorie (id_produit, id_categorie, niveau)
            VALUES (%s, %s, %s)
            ON CONFLICT (id_produit, id_categorie) DO UPDATE SET niveau = EXCLUDED.niveau
            """,
            (id_produit, cache[nom], niveau),
        )
        count += 1
    return count


# ── 4. ingredient_standardise ─────────────────────────────────────
def upsert_ingredient_standardise(cur, nom_canonique: str, nom_brut, cache: dict) -> int:
    """
    [FIX-3] ON CONFLICT DO UPDATE avec COALESCE pour préserver nom_brut existant.
    RETURNING id_ingredient évite un SELECT supplémentaire.
    """
    if nom_canonique in cache:
        return cache[nom_canonique]
    cur.execute(
        """
        INSERT INTO ingredient_standardise (nom_canonique, nom_ingredient_brut)
        VALUES (%s, %s)
        ON CONFLICT (nom_canonique) DO UPDATE
            SET nom_ingredient_brut = COALESCE(
                EXCLUDED.nom_ingredient_brut,
                ingredient_standardise.nom_ingredient_brut
            )
        RETURNING id_ingredient
        """,
        (nom_canonique, nom_brut),
    )
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "SELECT id_ingredient FROM ingredient_standardise WHERE nom_canonique = %s",
            (nom_canonique,)
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"upsert_ingredient_standardise : introuvable pour {nom_canonique!r}")
    cache[nom_canonique] = row[0]
    return cache[nom_canonique]


# ── 4b. ingredient_synonyme ───────────────────────────────────────
def insert_synonyms(cur, id_ingredient: int, synonyms: list, nom_canonique: str = "") -> None:
    """
    [FIX-2] Normalisation : lower/strip, dédoublonnage Python, skip si == canonique.
    """
    seen: set = set()
    for syn in synonyms:
        syn = clean_text(syn)
        if not syn:
            continue
        syn = syn.lower().strip()
        if syn in seen:
            continue
        seen.add(syn)
        if nom_canonique and syn == nom_canonique.lower().strip():
            continue
        cur.execute(
            """
            INSERT INTO ingredient_synonyme (nom_synonyme, langue, id_ingredient)
            VALUES (%s, NULL, %s)
            ON CONFLICT (nom_synonyme, langue) DO NOTHING
            """,
            (syn, id_ingredient),
        )


# ── 5. contient ───────────────────────────────────────────────────
def upsert_contient(cur, id_produit: int, id_ingredient: int, ordre: int, niveau: int) -> int:
    cur.execute(
        """
        INSERT INTO contient (id_produit, id_ingredient, ordre, niveau)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (id_produit, ordre) DO UPDATE SET
            id_ingredient = EXCLUDED.id_ingredient,
            niveau        = EXCLUDED.niveau
        RETURNING id_contient
        """,
        (id_produit, id_ingredient, ordre, niveau),
    )
    result = cur.fetchone()
    if result:
        return result[0]
    cur.execute(
        "SELECT id_contient FROM contient WHERE id_produit = %s AND ordre = %s",
        (id_produit, ordre),
    )
    return cur.fetchone()[0]


# ── 6. sous_ingredient ────────────────────────────────────────────
def upsert_sous_ingredient(
    cur,
    id_ingredient_enfant: int,
    ordre_enfant: int,
    niveau: int,
    id_contient_parent=None,
    id_sous_parent=None,
):
    cur.execute(
        """
        INSERT INTO sous_ingredient
            (id_contient_parent, id_sous_parent, id_ingredient_enfant, ordre_enfant, niveau)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING id_sous_ingredient
        """,
        (id_contient_parent, id_sous_parent, id_ingredient_enfant, ordre_enfant, niveau),
    )
    result = cur.fetchone()
    if result:
        return result[0]
    if id_contient_parent is not None:
        cur.execute(
            """
            SELECT id_sous_ingredient FROM sous_ingredient
            WHERE id_contient_parent = %s AND id_ingredient_enfant = %s LIMIT 1
            """,
            (id_contient_parent, id_ingredient_enfant),
        )
    else:
        cur.execute(
            """
            SELECT id_sous_ingredient FROM sous_ingredient
            WHERE id_sous_parent = %s AND id_ingredient_enfant = %s LIMIT 1
            """,
            (id_sous_parent, id_ingredient_enfant),
        )
    row = cur.fetchone()
    return row[0] if row else None


# ── 7. synonymes helpers ──────────────────────────────────────────
def _parse_synonyms_string(raw_synonyms: str) -> list:
    """
    Parse "sugar|sucrose, chocolate|dark chocolate, ..."
    Séparateur groupes : ", "  |  Séparateur interne : "|"
    Retourne : [ ["sugar","sucrose"], ["chocolate","dark chocolate"], ... ]
    """
    if not raw_synonyms or not str(raw_synonyms).strip():
        return []
    raw = str(raw_synonyms).strip()
    if ", " in raw:
        group_strings = [g.strip() for g in raw.split(", ") if g.strip()]
    else:
        group_strings = [g.strip() for g in raw.split(",") if g.strip()]
    result = []
    for grp in group_strings:
        syns = [s.strip() for s in grp.split("|") if s.strip()]
        seen, unique = set(), []
        for s in syns:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        result.append(unique)
    return result


def _align_synonyms_to_standardized(items_std: list, items_syn_raw: list, id_produit: int) -> list:
    n_std = len(items_std)
    n_syn = len(items_syn_raw)
    if n_syn == n_std:
        return items_syn_raw
    mon_warn(
        "[synonymes] désalignement",
        f"std={n_std}  synonymes={n_syn}  →  ajustement | produit id={id_produit}",
    )
    if n_syn > n_std:
        return items_syn_raw[:n_std]
    return items_syn_raw + [[] for _ in range(n_std - n_syn)]


# ── 8. load_ingredients ───────────────────────────────────────────
def load_ingredients(cur, id_produit: int, row, cache_std: dict):
    """
    Charge les ingrédients dans contient et sous_ingredient.
    Retourne (nb_contient, nb_sous_ingredient).

    [FIX-1] ALIGNEMENT CORRIGÉ
    ──────────────────────────────────────────────────────────────
    PROBLÈME ORIGINAL :
      brut_to_canonical croisait items[i] (hiérarchique) avec
      items_std[i] (plat LLM) → indices désalignés dès qu'il y a
      des parenthèses dans ingredients_text.
      Résultat : "sugar" → "oil", "dried cream cheese" → "wholemeal
      wheat flour", etc. → table ingredient_standardise corrompue.

    SOLUTION : std_index_for_niveau1
      Compteur dédié qui n'avance QUE sur les items de niveau 1.
      Sous-ingrédients (niveau 2+) = fallback brut (documenté, loggé).
    ──────────────────────────────────────────────────────────────
    """
    raw_text         = clean_text(safe_col(row, "ingredients_text"))
    raw_standardized = clean_text(safe_col(row, "ingredients_standardized"))
    raw_synonyms     = safe_col(row, "ingredients_synonyms")

    if not raw_text:
        return 0, 0

    # ── Étape 1 : parsing hiérarchique ──────────────────────────
    items   = parse_ingredients_hierarchiques(raw_text)
    n_items = len(items)

    # ── Étape 2 : noms canoniques (standardized, plat) ──────────
    if raw_standardized:
        if ", " in raw_standardized:
            items_std = [s.strip() for s in raw_standardized.split(", ") if s.strip()]
        else:
            items_std = split_values(raw_standardized)
    else:
        items_std = []
    n_std = len(items_std)

    # Monitoring alignement
    n_niveau1 = sum(1 for it in items if it["niveau"] == 1)
    if n_std == 0:
        mon_warn(
            "[ingredients] ingredients_standardized vide",
            f"fallback brut pour {n_items} items | produit id={id_produit}",
        )
    elif n_std != n_niveau1:
        mon_warn(
            "[ingredients] désalignement niveau1↔std",
            f"niveau1={n_niveau1}  std={n_std}  total_items={n_items} | produit id={id_produit}",
        )
    else:
        mon_info(
            "[ingredients] alignement OK",
            f"niveau1={n_niveau1}  std={n_std}  total_items={n_items}",
        )

    # ── Étape 3 : synonymes ──────────────────────────────────────
    if raw_synonyms is not None and str(raw_synonyms).strip():
        raw_syn_str = str(raw_synonyms).strip()
        mon_info(
            "[synonymes] parsing",
            raw_syn_str[:120] + ("…" if len(raw_syn_str) > 120 else ""),
        )
        parsed_syn = _parse_synonyms_string(raw_syn_str)
        mon_info("[synonymes] groupes parsés", str(len(parsed_syn)))
        ref_list = items_std if n_std > 0 else [it["nom"] for it in items if it["niveau"] == 1]
        items_syn = _align_synonyms_to_standardized(ref_list, parsed_syn, id_produit)
    else:
        mon_info("[synonymes]", "colonne absente ou vide → 0 synonymes")
        items_syn = [[] for _ in range(n_std if n_std > 0 else n_niveau1)]

    # ── Étape 4 : purge ciblée [FIX-4] ──────────────────────────
    new_ordres = {item["ordre"] for item in items if clean_text(item["nom"])}
    cur.execute("SELECT ordre FROM contient WHERE id_produit = %s", (id_produit,))
    existing_ordres  = {r[0] for r in cur.fetchall()}
    ordres_to_delete = existing_ordres - new_ordres
    if ordres_to_delete:
        cur.execute(
            "DELETE FROM contient WHERE id_produit = %s AND ordre = ANY(%s)",
            (id_produit, list(ordres_to_delete)),
        )
        mon_info(
            "[contient] purge ciblée",
            f"{len(ordres_to_delete)} ordres supprimés : {sorted(ordres_to_delete)}",
        )

    nb_contient = 0
    nb_sous     = 0
    niveau_to_id: dict = {}

    # [FIX-1] Compteur dédié aux items de niveau 1
    std_index_for_niveau1 = 0

    for i, item in enumerate(items):
        nom_brut = clean_text(item["nom"])
        ordre    = item["ordre"]
        niveau   = item["niveau"]

        if not nom_brut:
            continue

        # ── Étape 5 : résolution nom canonique [FIX-1] ──────────
        if niveau == 1:
            if std_index_for_niveau1 < n_std:
                nom_std       = items_std[std_index_for_niveau1]
                nom_canonique = nom_std.lower().strip() if nom_std else nom_brut.lower().strip()
                mon_info(
                    "[canonique]",
                    f"niv1 std[{std_index_for_niveau1}] "
                    f"brut='{nom_brut}' → canon='{nom_canonique}'",
                )
            else:
                nom_canonique = nom_brut.lower().strip()
                mon_warn(
                    "[canonique]",
                    f"niv1 std hors range (idx={std_index_for_niveau1}) "
                    f"brut='{nom_brut}' → fallback brut",
                )
            std_index_for_niveau1 += 1  # ← avancer UNIQUEMENT pour niveau 1
        else:
            # Sous-ingrédient : absent de items_std → fallback brut
            nom_canonique = nom_brut.lower().strip()
            mon_info(
                "[canonique]",
                f"niv{niveau} sous-ingr brut='{nom_brut}' → canon='{nom_canonique}' (fallback)",
            )

        # ── Étape 6 : upsert ingredient_standardise ──────────────
        id_ingredient = upsert_ingredient_standardise(cur, nom_canonique, nom_brut, cache_std)

        # ── Étape 7 : synonymes (niveau 1 uniquement) ────────────
        if niveau == 1:
            syn_index = std_index_for_niveau1 - 1
            syns = items_syn[syn_index] if 0 <= syn_index < len(items_syn) else []
            if syns:
                mon_info(
                    f"[synonymes] niv1 idx={syn_index} '{nom_canonique}'",
                    " | ".join(syns),
                )
                insert_synonyms(cur, id_ingredient, syns, nom_canonique=nom_canonique)

        # ── Étape 8 : insertion hiérarchique ─────────────────────
        if niveau == 1:
            id_contient = upsert_contient(cur, id_produit, id_ingredient, ordre, niveau)
            niveau_to_id[1] = id_contient
            nb_contient += 1

        elif niveau == 2:
            id_contient_parent = niveau_to_id.get(1)
            if id_contient_parent is None:
                mon_warn(
                    "[sous_ingredient] niveau 2 sans parent niveau 1",
                    f"ingr='{nom_canonique}' ordre={ordre} → ignoré",
                )
                continue
            id_sous = upsert_sous_ingredient(
                cur,
                id_ingredient_enfant=id_ingredient,
                ordre_enfant=ordre,
                niveau=niveau,
                id_contient_parent=id_contient_parent,
                id_sous_parent=None,
            )
            if id_sous is not None:
                niveau_to_id[2] = id_sous
            nb_sous += 1

        else:
            id_sous_parent = niveau_to_id.get(niveau - 1)
            if id_sous_parent is None:
                mon_warn(
                    f"[sous_ingredient] niveau {niveau} sans parent niveau {niveau - 1}",
                    f"ingr='{nom_canonique}' ordre={ordre} → ignoré",
                )
                continue
            id_sous = upsert_sous_ingredient(
                cur,
                id_ingredient_enfant=id_ingredient,
                ordre_enfant=ordre,
                niveau=niveau,
                id_contient_parent=None,
                id_sous_parent=id_sous_parent,
            )
            if id_sous is not None:
                niveau_to_id[niveau] = id_sous
            nb_sous += 1

    return nb_contient, nb_sous


# ── 9. traces ─────────────────────────────────────────────────────
def load_traces(cur, id_produit: int, row, cache: dict) -> int:
    count = 0
    for raw in split_values(row.get("traces_tags")):
        nom = normalize_tag(raw) or clean_text(raw)
        if not nom:
            continue
        if nom not in cache:
            cache[nom] = get_or_create(cur, "trace", "id_trace", "nom_trace", nom)
        cur.execute(
            "INSERT INTO produit_trace (id_produit, id_trace) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (id_produit, cache[nom]),
        )
        count += 1
    return count


# ── 10. allergenes ────────────────────────────────────────────────
def load_allergenes(cur, row, cache_trace: dict, cache_allergene: dict) -> int:
    allergens = split_values(row.get("allergens_tags"))
    if not allergens:
        return 0
    count = 0
    for raw_al in allergens:
        nom_al = normalize_tag(raw_al) or clean_text(raw_al)
        if not nom_al:
            continue
        if nom_al not in cache_allergene:
            cache_allergene[nom_al] = get_or_create(
                cur, "allergene", "id_allergene", "nom_allergene", nom_al
            )
        id_allergene = cache_allergene[nom_al]
        if nom_al not in cache_trace:
            cache_trace[nom_al] = get_or_create(
                cur, "trace", "id_trace", "nom_trace", nom_al
            )
        id_trace = cache_trace[nom_al]
        cur.execute(
            "INSERT INTO trace_allergene (id_trace, id_allergene) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (id_trace, id_allergene),
        )
        count += 1
    return count


# ══════════════════════════════════════════════════════════════════
# Monitoring wrappers (compatibilité avec les appels existants)
# ══════════════════════════════════════════════════════════════════
def step_ok(code: str, etape: str, detail: str = "") -> None:
    mon_ok(f"[{etape}]", detail)

def step_warn(code: str, etape: str, raison: str) -> None:
    mon_warn(f"[{etape}]", raison)

def step_fail(code: str, etape: str, exc: Exception) -> None:
    tb_short = "\n         ".join(traceback.format_exc().splitlines()[-5:])
    mon_err(f"[{etape}]", f"{type(exc).__name__}: {exc}")
    print(_c("dim", f"         {tb_short}"))

def check_missing_fields(row, code: str) -> list:
    checks = {
        "code":                     clean_text(row.get("code")),
        "product_name":             clean_text(row.get("product_name")),
        "brands":                   clean_text(row.get("brands")),
        "categories_tags":          row.get("categories_tags"),
        "nutriscore_grade":         clean_text(row.get("nutriscore_grade")),
        "nova_group":               clean_int(row.get("nova_group")),
        "ingredients_text":         clean_text(safe_col(row, "ingredients_text")),
        "ingredients_standardized": clean_text(safe_col(row, "ingredients_standardized")),
        "allergens_tags":           row.get("allergens_tags"),
        "traces_tags":              row.get("traces_tags"),
        "saturated_fat_100g":       clean_float(row.get("saturated_fat_100g")),
        "sugars_100g":              clean_float(row.get("sugars_100g")),
        "salt_100g":                clean_float(row.get("salt_100g")),
        "image_url":                clean_text(row.get("image_url")),
    }
    return [k for k, v in checks.items() if is_missing(v)]


# ══════════════════════════════════════════════════════════════════
# Core loader
# ══════════════════════════════════════════════════════════════════
def load_dataframe_rows(cur, df, stats: dict, caches: dict, batch_index: int = 0) -> None:
    batch_start   = time.time()
    rows_in_batch = len(df)
    stats["rows_input"] += rows_in_batch

    mon_header(f"Batch #{batch_index}  ·  {rows_in_batch} lignes")
    mon_info("Colonnes Parquet", str(len(df.columns)))
    print(_c("dim", f"    {list(df.columns)}"))

    important_cols = [
        "code", "product_name", "brands", "categories_tags",
        "ingredients_text", "ingredients_standardized",
        "allergens_tags", "traces_tags", "nutriscore_grade", "nova_group",
    ]
    missing_parquet = [c for c in important_cols if c not in df.columns]
    if missing_parquet:
        mon_warn("COLONNES ABSENTES DU PARQUET", ", ".join(missing_parquet))
        mon_warn("Ces champs seront NULL pour toutes les lignes")

    batch_skipped = 0
    batch_stats = {
        "marque_null": 0, "cat_null": 0,
        "ingr_text_null": 0, "ingr_std_null": 0,
        "traces_null": 0, "allergens_null": 0,
        "fields_warn_total": 0,
    }

    for idx, row in df.iterrows():
        code_barre  = clean_text(row.get("code"))
        nom_produit = clean_text(row.get("product_name"))

        if not code_barre or not nom_produit:
            stats["rows_skipped"] += 1
            batch_skipped += 1
            mon_skip(
                "SKIP",
                f"idx={idx}  "
                f"code={'MANQUANT' if not code_barre else code_barre!r}  "
                f"nom={'MANQUANT' if not nom_produit else nom_produit!r}",
            )
            continue

        mon_produit_header(code_barre, nom_produit or "", idx)

        manquants = check_missing_fields(row, code_barre)
        if manquants:
            mon_warn("Champs NULL/vides", ", ".join(manquants))
            batch_stats["fields_warn_total"] += len(manquants)
            stats["fields_warnings"] = stats.get("fields_warnings", 0) + len(manquants)

        id_produit = None
        action     = "?"

        try:
            # ── 1. MARQUE ────────────────────────────────────────
            brand = clean_text(row.get("brands"))
            try:
                id_marque = upsert_marque(cur, brand, caches["marque"]) if brand else None
                if id_marque:
                    step_ok(code_barre, "marque", f"'{brand}' → id={id_marque}")
                else:
                    step_warn(code_barre, "marque", "brands vide → id_marque=NULL")
                    batch_stats["marque_null"] += 1
            except Exception as e:
                step_fail(code_barre, "marque", e)
                raise

            # ── 2. PRODUIT ───────────────────────────────────────
            try:
                cur.execute(
                    "SELECT id_produit FROM produit WHERE code_barre = %s LIMIT 1",
                    (code_barre,)
                )
                existing   = cur.fetchone()
                id_produit = upsert_produit(cur, row, id_marque)
                action     = "UPDATE" if existing else "INSERT"
                stats["products_updated" if existing else "products_inserted"] += 1
                step_ok(code_barre, "produit", f"{action} → id_produit={id_produit}")
            except Exception as e:
                step_fail(code_barre, "produit", e)
                raise

            # ── 3. CATEGORIES ────────────────────────────────────
            try:
                nb_cat = load_categories(cur, id_produit, row, caches["categorie"])
                if nb_cat > 0:
                    step_ok(code_barre, "produit_categorie", f"{nb_cat} catégories liées")
                else:
                    step_warn(code_barre, "produit_categorie", "categories_tags vide → 0 catégories")
                    batch_stats["cat_null"] += 1
            except Exception as e:
                step_fail(code_barre, "produit_categorie", e)
                raise

            # ── 4. INGREDIENTS ───────────────────────────────────
            try:
                raw_std = clean_text(safe_col(row, "ingredients_standardized"))
                nb_contient, nb_sous = load_ingredients(
                    cur, id_produit, row, caches["ingredient_std"]
                )
                if nb_contient > 0:
                    step_ok(
                        code_barre, "contient",
                        f"{nb_contient} ingrédients niveau 1 | {nb_sous} sous-ingrédients",
                    )
                else:
                    step_warn(code_barre, "contient", "ingredients_text vide → 0 ingrédients")
                    batch_stats["ingr_text_null"] += 1
                if not raw_std:
                    step_warn(
                        code_barre, "ingredients_standardized",
                        "colonne absente ou vide → noms bruts utilisés comme canonique",
                    )
                    batch_stats["ingr_std_null"] += 1
            except Exception as e:
                step_fail(code_barre, "contient/sous_ingredient", e)
                raise

            # ── 5. TRACES ────────────────────────────────────────
            try:
                nb_tr = load_traces(cur, id_produit, row, caches["trace"])
                if nb_tr > 0:
                    step_ok(code_barre, "produit_trace", f"{nb_tr} traces liées")
                else:
                    step_warn(code_barre, "produit_trace", "traces_tags vide → 0 traces")
                    batch_stats["traces_null"] += 1
            except Exception as e:
                step_fail(code_barre, "produit_trace", e)
                raise

            # ── 6. ALLERGENES ────────────────────────────────────
            try:
                nb_al = load_allergenes(cur, row, caches["trace"], caches["allergene"])
                if nb_al > 0:
                    step_ok(code_barre, "trace_allergene", f"{nb_al} allergènes liés")
                else:
                    step_warn(code_barre, "trace_allergene", "allergens_tags vide → 0 allergènes")
                    batch_stats["allergens_null"] += 1
            except Exception as e:
                step_fail(code_barre, "trace_allergene", e)
                raise

            stats["rows_loaded"] += 1
            mon_produit_footer(code_barre, action, nb_cat, nb_contient, nb_sous, nb_tr, nb_al)

        except Exception as exc:
            mon_err(f"PRODUIT {code_barre} IGNORÉ", f"{type(exc).__name__}: {exc}")
            stats["rows_skipped"] += 1
            batch_skipped += 1

    elapsed = time.time() - batch_start
    mon_batch_summary(batch_index, rows_in_batch, batch_skipped, elapsed, batch_stats)


# ══════════════════════════════════════════════════════════════════
# Orchestrateur
# ══════════════════════════════════════════════════════════════════
def load_parquet_to_postgres(parquet_path: str, schema_sql_path=None, batch_size: int = 5000, **kwargs) -> dict:
    mon_header("SILVER → GOLD  |  Chargement Parquet → PostgreSQL")
    mon_info("Fichier",    parquet_path)
    mon_info("Batch size", str(batch_size))

    global_start = time.time()
    conn = get_pg_connection()

    stats = {
        "rows_input": 0, "rows_loaded": 0, "rows_skipped": 0,
        "products_inserted": 0, "products_updated": 0,
    }
    caches = {
        "marque": {}, "categorie": {},
        "ingredient_std": {},
        "trace": {}, "allergene": {},
    }

    try:
        with conn.cursor() as cur:
            ensure_schema(cur, schema_sql_path=schema_sql_path)
        conn.commit()
        mon_ok("Schéma validé et commit effectué")

        with conn:
            with conn.cursor() as cur:
                mon_section("Ouverture du fichier Parquet")
                mon_info("Chemin", parquet_path)
                pf       = pq.ParquetFile(parquet_path)
                metadata = pf.metadata
                mon_ok(
                    "Parquet ouvert",
                    f"{metadata.num_rows} lignes  ·  {metadata.num_row_groups} row groups",
                )
                print(_c("dim", f"\n{pf.schema_arrow}\n"))

                batch_index = 0
                for batch in pf.iter_batches(batch_size=batch_size):
                    batch_index += 1
                    df = batch.to_pandas()
                    load_dataframe_rows(cur, df, stats=stats, caches=caches, batch_index=batch_index)
                    conn.commit()
                    progress = mon_progress_bar(stats["rows_loaded"], stats["rows_input"])
                    mon_ok(
                        f"COMMIT Batch #{batch_index}",
                        f"{progress}  {stats['rows_loaded']}/{stats['rows_input']}",
                    )

    finally:
        conn.close()
        mon_info("Connexion PostgreSQL fermée")

    elapsed = time.time() - global_start
    mon_header(f"RÉSUMÉ GLOBAL  ·  {mon_timer(elapsed)}")
    mon_table([
        ("rows_input",        stats["rows_input"]),
        ("rows_loaded",       stats["rows_loaded"]),
        ("rows_skipped",      stats["rows_skipped"]),
        ("products_inserted", stats["products_inserted"]),
        ("products_updated",  stats["products_updated"]),
    ])
    mon_separator()
    mon_cache_summary(caches)
    return stats


# ══════════════════════════════════════════════════════════════════
# Airflow callable
# ══════════════════════════════════════════════════════════════════
def load_silver_to_postgres(input_key: str, input_bucket=None, schema_sql_path=None, **kwargs):
    if input_bucket is None:
        input_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")

    mon_header("Airflow  ·  load_silver_to_postgres")
    mon_info("Bucket", input_bucket)
    mon_info("Clé",    input_key)

    s3 = get_s3_client()
    try:
        head    = s3.head_object(Bucket=input_bucket, Key=input_key)
        size_mb = head["ContentLength"] / 1_048_576
        mon_ok("Objet MinIO trouvé", f"{size_mb:.2f} MB")
    except Exception as e:
        mon_err("Objet MinIO introuvable", str(e))
        raise

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        parquet_path = tmp.name

    try:
        mon_info("Téléchargement", f"{input_bucket}/{input_key}  →  {parquet_path}")
        s3.download_file(input_bucket, input_key, parquet_path)
        mon_ok("Téléchargement terminé", parquet_path)
        stats = load_parquet_to_postgres(parquet_path, schema_sql_path=schema_sql_path)
    finally:
        if os.path.exists(parquet_path):
            os.remove(parquet_path)
            mon_info("Fichier temporaire supprimé", parquet_path)

    mon_ok("Airflow terminé", f"{stats['rows_loaded']} produits chargés")
    return {
        "loaded_rows": stats["rows_loaded"],
        "bucket": input_bucket,
        "key": input_key,
        **stats,
    }


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════
def main():
    args = parse_args()
    load_silver_to_postgres(
        input_bucket=args.input_bucket,
        input_key=args.input_key,
        schema_sql_path=args.schema_sql,
    )

if __name__ == "__main__":
    main()