"""Comparateur de produits — schéma v3.

Changements :
- JOIN sur produit.id_produit (PK SERIAL) via code_barre
- Valeurs nutritionnelles directement dans produit
- Pas de table valeurs_nutritionnelles
"""

import sys
import warnings
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection
from health_logic import HealthProfile, compute_personalized_scores
from top_menu import render_top_menu

st.set_page_config(page_title="Comparateur de produits", layout="wide", initial_sidebar_state="collapsed")
render_top_menu("Dashboard")

st.title("Comparateur de produits")
st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)

if "compare_selection" not in st.session_state or not st.session_state.compare_selection:
    st.info("Aucun produit sélectionné. Retournez au Dashboard et cochez \"Comparer\" sur 2 à 3 produits.")
    st.stop()

codes = [str(c) for c in st.session_state.compare_selection]

if len(codes) < 2:
    st.info("Sélectionnez au moins 2 produits pour comparer.")
    st.stop()

if len(codes) > 3:
    codes = codes[:3]
    st.warning("Seuls les 3 premiers produits sélectionnés sont comparés.")

conn = get_connection()
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning)

placeholders = ",".join(["%s"] * len(codes))

# Recherche par code_barre (identifiant externe) OU id_produit::text
QUERY = f"""
SELECT
    p.id_produit,
    COALESCE(p.code_barre, p.id_produit::text) AS code,
    p.nom_produit                               AS product_name,
    p.categorie_principale,
    p.nutrition_grade                           AS nutriscore_grade,
    p.nova_group,
    p.sugars_100g,
    p.salt_100g,
    p.saturated_fat_100g,
    p.fiber_100g,
    p.proteins_100g
FROM produit p
WHERE p.code_barre IN ({placeholders})
   OR p.id_produit::text IN ({placeholders})
"""

compare_df = pd.read_sql(QUERY, conn, params=tuple(codes) * 2)

# Déduplication si le même produit est trouvé par les deux critères
compare_df = compare_df.drop_duplicates(subset=["id_produit"])

if compare_df.empty:
    st.error("Impossible de charger les produits sélectionnés.")
    st.stop()

# Score personnalisé
health_profile    = st.session_state.get("health_profile")
use_health_profile = st.session_state.get("use_health_profile", False)

if use_health_profile and isinstance(health_profile, HealthProfile):
    try:
        scores = compute_personalized_scores(compare_df, health_profile)
        compare_df = compare_df.assign(personal_score=scores)
    except Exception as e:
        st.warning(f"Impossible de calculer le score personnalisé : {e}")
        compare_df["personal_score"] = pd.NA
else:
    compare_df["personal_score"] = pd.NA

# ── Affichage colonnes ────────────────────────────────────────────

cols = st.columns(len(compare_df))

for col, (_, row) in zip(cols, compare_df.iterrows()):
    with col:
        st.subheader(str(row["product_name"]))
        st.caption(f"Code : {row['code']}")
        st.markdown(f"**Catégorie principale :** {row.get('categorie_principale') or 'autres'}")
        st.markdown(f"**NutriScore :** {row.get('nutriscore_grade', 'N/A')}")
        st.markdown(f"**Groupe NOVA :** {row.get('nova_group', 'N/A')}")
        st.markdown("---")
        st.markdown("**Profil nutritionnel (pour 100g)**")
        st.markdown(f"- Sucre : {row.get('sugars_100g', 'N/A')} g")
        st.markdown(f"- Sel : {row.get('salt_100g', 'N/A')} g")
        st.markdown(f"- Graisses saturées : {row.get('saturated_fat_100g', 'N/A')} g")
        st.markdown(f"- Fibres : {row.get('fiber_100g', 'N/A')} g")
        st.markdown(f"- Protéines : {row.get('proteins_100g', 'N/A')} g")
        if pd.notna(row.get("personal_score")):
            st.markdown("---")
            st.markdown(f"**Score santé personnalisé :** {row['personal_score']:.2f}")

st.markdown("---")

# ── Meilleur produit ──────────────────────────────────────────────

best_row = None
reason   = None

if compare_df["personal_score"].notna().any():
    idx      = compare_df["personal_score"].idxmax()
    best_row = compare_df.loc[idx]
    reason   = "score santé personnalisé"
else:
    mapping = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}
    nutri_numeric = (
        compare_df["nutriscore_grade"].fillna("").astype(str).str.upper()
        .map(mapping).fillna(0.0)
    )
    if nutri_numeric.max() > 0:
        idx      = nutri_numeric.idxmax()
        best_row = compare_df.loc[idx]
        reason   = "NutriScore"

if best_row is not None:
    st.subheader("Meilleur choix parmi ces produits")
    cat = best_row.get("categorie_principale") or "autres"
    st.markdown(
        f"**{best_row['product_name']}** (code {best_row['code']})\n\n"
        f"- Catégorie principale : {cat}\n"
        f"- NutriScore : {best_row.get('nutriscore_grade', 'N/A')}\n"
        f"- Groupe NOVA : {best_row.get('nova_group', 'N/A')}\n"
        + (f"- Score santé personnalisé : {best_row['personal_score']:.2f}\n"
           if pd.notna(best_row.get("personal_score")) else "")
    )
    if reason:
        st.caption(f"Meilleur produit déterminé selon : {reason}.")
