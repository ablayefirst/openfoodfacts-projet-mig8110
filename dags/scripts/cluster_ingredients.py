#!/usr/bin/env python3
"""Cluster raw ingredients and elect a standardized representative per cluster.

Algorithm:
  1. Load all ingredients + their frequency in produit_ingredient.
  2. Vectorize names with TF-IDF (character n-grams 2-4).
  3. Cluster with DBSCAN using cosine distance.
  4. Per cluster: elect the most frequent ingredient as the standardized form.
  5. Write the representative to ingredient_standardise.
  6. Write the other cluster members to synonyme_ingredient (source='cluster').
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

import numpy as np
import psycopg2
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

DEFAULT_SIMILARITY = float(os.getenv("INGREDIENT_CLUSTER_SIMILARITY", "0.80"))
DEFAULT_MIN_SAMPLES = int(os.getenv("INGREDIENT_CLUSTER_MIN_SAMPLES", "2"))
DEFAULT_MIN_FREQ = int(os.getenv("INGREDIENT_CLUSTER_MIN_FREQ", "2"))
DEFAULT_BATCH_SIZE = int(os.getenv("INGREDIENT_CLUSTER_BATCH_SIZE", "5000"))


# ──────────────────────────────────────────────
# DB
# ──────────────────────────────────────────────

def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "openfood_db"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres123"),
    )


# ──────────────────────────────────────────────
# Text normalization
# ──────────────────────────────────────────────

def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).strip().lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9 ]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


# ──────────────────────────────────────────────
# Load ingredients with frequency
# ──────────────────────────────────────────────

def load_ingredients(conn, min_freq: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                i.id_ingredient,
                i.ingredients_nom,
                COUNT(pi.code_produit) AS frequence
            FROM ingredient i
            LEFT JOIN produit_ingredient pi ON pi.id_ingredient = i.id_ingredient
            WHERE i.ingredients_nom IS NOT NULL
              AND TRIM(i.ingredients_nom) <> ''
            GROUP BY i.id_ingredient, i.ingredients_nom
            HAVING COUNT(pi.code_produit) >= %s
            ORDER BY frequence DESC, i.ingredients_nom
        """, (min_freq,))
        rows = cur.fetchall()

    return [
        {
            "id_ingredient": row[0],
            "nom_original": row[1],
            "nom_normalise": normalize_name(row[1]),
            "frequence": int(row[2]),
        }
        for row in rows
        if normalize_name(row[1])
    ]


# ──────────────────────────────────────────────
# Clustering
# ──────────────────────────────────────────────

def cluster_ingredients(
    ingredients: list[dict[str, Any]],
    similarity_threshold: float,
    min_samples: int,
) -> dict[int, list[dict[str, Any]]]:
    names = [ing["nom_normalise"] for ing in ingredients]

    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        min_df=1,
        sublinear_tf=True,
    )
    tfidf_matrix = vectorizer.fit_transform(names)
    tfidf_matrix = normalize(tfidf_matrix, norm="l2")

    eps = 1.0 - similarity_threshold

    dbscan = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        metric="cosine",
        algorithm="brute",
        n_jobs=-1,
    )
    labels = dbscan.fit_predict(tfidf_matrix)

    clusters: dict[int, list[dict[str, Any]]] = {}
    for idx, label in enumerate(labels):
        ing = ingredients[idx].copy()
        label = int(label)
        ing["cluster_label"] = label
        if label == -1:
            singleton_key = -(idx + 10000)
            clusters[singleton_key] = [ing]
        else:
            clusters.setdefault(label, []).append(ing)

    return clusters


# ──────────────────────────────────────────────
# Elect representative
# ──────────────────────────────────────────────

def elect_representative(members: list[dict[str, Any]]) -> dict[str, Any]:
    return max(members, key=lambda x: (x["frequence"], -len(x["nom_normalise"])))


# ──────────────────────────────────────────────
# Persist
# ──────────────────────────────────────────────

def upsert_standardise(cur, nom: str, frequence: int, cluster_id: int) -> int:
    cur.execute("""
        INSERT INTO ingredient_standardise (nom_standardise, frequence, cluster_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (nom_standardise) DO UPDATE
            SET frequence  = EXCLUDED.frequence,
                cluster_id = EXCLUDED.cluster_id
        RETURNING id_standardise
    """, (nom, frequence, cluster_id))
    return int(cur.fetchone()[0])


def upsert_synonyme(cur, nom: str, id_ingredient: int, id_standardise: int) -> None:
    cur.execute("""
        SELECT id_synonyme FROM synonyme_ingredient
        WHERE LOWER(TRIM(nom_synonyme)) = LOWER(TRIM(%s))
        LIMIT 1
    """, (nom,))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE synonyme_ingredient
            SET id_standardise = %s,
                source = 'cluster',
                relation_type = 'variante'
            WHERE id_synonyme = %s
        """, (id_standardise, existing[0]))
    else:
        cur.execute("""
            INSERT INTO synonyme_ingredient
                (nom_synonyme, id_ingredient, id_standardise, source, relation_type, confidence)
            VALUES (%s, %s, %s, 'cluster', 'variante', 1.0)
            ON CONFLICT DO NOTHING
        """, (nom, id_ingredient, id_standardise))


def persist_clusters(
    conn,
    clusters: dict[int, list[dict[str, Any]]],
) -> dict[str, int]:
    stats = {"clusters": 0, "standardises": 0, "synonymes": 0, "singletons": 0}

    with conn.cursor() as cur:
        for cluster_id, members in clusters.items():
            is_singleton = cluster_id < 0

            rep = elect_representative(members)
            nom_std = rep["nom_original"].strip()

            total_freq = int(sum(m["frequence"] for m in members))
            id_std = upsert_standardise(cur, nom_std, total_freq, int(cluster_id))
            stats["standardises"] += 1

            if is_singleton:
                stats["singletons"] += 1
            else:
                stats["clusters"] += 1

            for member in members:
                if member["id_ingredient"] == rep["id_ingredient"]:
                    continue
                upsert_synonyme(cur, member["nom_original"], member["id_ingredient"], id_std)
                stats["synonymes"] += 1

    conn.commit()
    return stats


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def cluster_ingredient_synonyms(
    similarity_threshold: float = DEFAULT_SIMILARITY,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_freq: int = DEFAULT_MIN_FREQ,
    dry_run: bool = False,
) -> dict[str, Any]:
    conn = get_connection()
    try:
        print(f"Chargement des ingrédients (fréquence >= {min_freq})...")
        ingredients = load_ingredients(conn, min_freq)
        print(f"{len(ingredients)} ingrédients chargés.")

        if not ingredients:
            return {"ingredients": 0, "clusters": 0, "standardises": 0, "synonymes": 0}

        print(f"Clustering (seuil similarité={similarity_threshold}, min_samples={min_samples})...")
        clusters = cluster_ingredients(ingredients, similarity_threshold, min_samples)

        real_clusters = sum(1 for k in clusters if k >= 0)
        singletons = sum(1 for k in clusters if k < 0)
        print(f"{real_clusters} clusters trouvés, {singletons} singletons (bruit).")

        if dry_run:
            print("Dry-run: aperçu des 5 premiers clusters :")
            shown = 0
            for cid, members in clusters.items():
                if cid < 0 or shown >= 5:
                    continue
                rep = elect_representative(members)
                synonymes = [m["nom_original"] for m in members if m["id_ingredient"] != rep["id_ingredient"]]
                print(f"  [{cid}] Standardisé: '{rep['nom_original']}' (freq={rep['frequence']}) | Synonymes: {synonymes}")
                shown += 1
            return {
                "ingredients": len(ingredients),
                "clusters": real_clusters,
                "singletons": singletons,
                "standardises": 0,
                "synonymes": 0,
            }

        print("Écriture en base...")
        stats = persist_clusters(conn, clusters)
        stats["ingredients"] = len(ingredients)

        print(f"Terminé: {stats['standardises']} standardisés, {stats['synonymes']} synonymes écrits.")
        return stats

    finally:
        conn.close()


if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Cluster raw ingredients into standardized forms.")
    parser.add_argument("--similarity", type=float, default=DEFAULT_SIMILARITY)
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--min-freq", type=int, default=DEFAULT_MIN_FREQ)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = cluster_ingredient_synonyms(
        similarity_threshold=args.similarity,
        min_samples=args.min_samples,
        min_freq=args.min_freq,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
