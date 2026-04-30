#!/usr/bin/env python3
"""Standardize ingredients in two steps:

  1. Clustering (always) — group similar raw ingredients, elect the most
     frequent as the canonical representative, store in ingredient_standardise,
     and write cluster members as synonyms (source='cluster').

  2. LLM enrichment (optional) — generate English canonical names and
     additional synonyms for the elected representatives.
     Activated by ENABLE_LLM_INGREDIENT_SYNONYMS=true.
     Skipped gracefully if the variable is absent or false.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from scripts.cluster_ingredients import cluster_ingredient_synonyms
    from scripts.generate_ingredient_synonyms import generate_ingredient_synonyms, get_pg_connection
except ModuleNotFoundError as exc:
    if exc.name not in {"scripts", "scripts.cluster_ingredients", "scripts.generate_ingredient_synonyms"}:
        raise
    from cluster_ingredients import cluster_ingredient_synonyms
    from generate_ingredient_synonyms import generate_ingredient_synonyms, get_pg_connection


DEFAULT_CACHE_PATH = os.getenv(
    "INGREDIENT_SYNONYM_CACHE_PATH",
    os.path.join(os.getenv("AIRFLOW_HOME", "/opt/airflow"), "data", "cache_ingredient_synonyms.json"),
)


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _fetch_standardise_candidates(limit: int, include_existing: bool) -> list[tuple[int, str]]:
    """Fetch canonical representatives from ingredient_standardise for the LLM step."""
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            where_extra = ""
            if not include_existing:
                where_extra = """
                  AND NOT EXISTS (
                      SELECT 1 FROM synonyme_ingredient s
                      WHERE s.id_standardise = ist.id_standardise
                        AND s.source = 'llm'
                  )
                """
            cur.execute(
                f"""
                SELECT ist.id_standardise, ist.nom_standardise
                FROM ingredient_standardise ist
                WHERE TRIM(ist.nom_standardise) <> ''
                  {where_extra}
                ORDER BY ist.frequence DESC, LENGTH(ist.nom_standardise)
                LIMIT %s
                """,
                (limit,),
            )
            return [(int(row[0]), str(row[1])) for row in cur.fetchall()]
    finally:
        conn.close()


def standardize_ingredients(
    similarity_threshold: float = float(os.getenv("INGREDIENT_CLUSTER_SIMILARITY", "0.80")),
    min_samples: int = int(os.getenv("INGREDIENT_CLUSTER_MIN_SAMPLES", "2")),
    min_freq: int = int(os.getenv("INGREDIENT_CLUSTER_MIN_FREQ", "2")),
    cluster_dry_run: bool = _env_bool("INGREDIENT_CLUSTER_DRY_RUN"),
    llm_limit: int = int(os.getenv("INGREDIENT_SYNONYM_LIMIT", "100")),
    llm_batch_size: int = int(os.getenv("INGREDIENT_SYNONYM_BATCH_SIZE", "20")),
    llm_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    llm_cache_path: str = DEFAULT_CACHE_PATH,
    llm_dry_run: bool = _env_bool("INGREDIENT_SYNONYM_DRY_RUN"),
    llm_include_existing: bool = _env_bool("INGREDIENT_SYNONYM_INCLUDE_EXISTING"),
) -> dict[str, Any]:

    stats: dict[str, Any] = {}

    # ── Étape 1 : Clustering (toujours actif) ─────────────────────────────
    print("=" * 50)
    print("Étape 1 — Clustering des ingrédients")
    print("=" * 50)
    cluster_stats = cluster_ingredient_synonyms(
        similarity_threshold=similarity_threshold,
        min_samples=min_samples,
        min_freq=min_freq,
        dry_run=cluster_dry_run,
    )
    stats["clustering"] = cluster_stats
    print(f"Clustering terminé : {cluster_stats}")

    # ── Étape 2 : LLM (optionnel) ─────────────────────────────────────────
    if not _env_bool("ENABLE_LLM_INGREDIENT_SYNONYMS"):
        print("\nLLM désactivé (ENABLE_LLM_INGREDIENT_SYNONYMS=false). Étape ignorée.")
        stats["llm"] = {"skipped": True}
        return stats

    print("\n" + "=" * 50)
    print("Étape 2 — Enrichissement LLM des représentants")
    print("=" * 50)

    llm_stats = generate_ingredient_synonyms(
        limit=llm_limit,
        batch_size=llm_batch_size,
        model=llm_model,
        cache_path=llm_cache_path,
        dry_run=llm_dry_run,
        preview_only=False,
        include_existing=llm_include_existing,
        candidate_fetcher=_fetch_standardise_candidates,
        candidate_kind="standardise",
    )
    stats["llm"] = llm_stats
    print(f"LLM terminé : {llm_stats}")

    return stats


if __name__ == "__main__":
    import json
    result = standardize_ingredients()
    print("\n── Résultat final ──")
    print(json.dumps(result, ensure_ascii=False, indent=2))
