# config.py
"""
Configuration centrale pour le module ingredients_ai
"""
import os

# ── LLM ──────────────────────────────────────────────────────────
USE_LLM        = True
LLM_BATCH_SIZE = 5

ENABLE_LLM_CACHE = True
# Chemin absolu basé sur la variable d'env AIRFLOW_HOME si dispo
# sinon /opt/airflow/data — évite les problèmes de chemin relatif dans Airflow
LLM_CACHE_PATH = os.path.join(
    os.getenv("AIRFLOW_HOME", "/opt/airflow"),
    "data",
    "cache_llm.json"
)

# ── EMBEDDING ────────────────────────────────────────────────────
EMBEDDING_THRESHOLD = 0.80
# 0.80 = bon équilibre précision/rappel avec les noms bruts comme référence
# (était 0.85 — trop strict, ratait trop d'ingrédients légitimes)

# ── QUALITÉ ──────────────────────────────────────────────────────
QUALITY_THRESHOLD = 70

# ── PERFORMANCE ──────────────────────────────────────────────────
MAX_INGREDIENTS = 60

# ── DEBUG / MONITORING ───────────────────────────────────────────
ENABLE_LOGGING = True
SHOW_STATS     = True