import warnings

import pandas as pd
import streamlit as st

from db_connection import get_connection
from health_logic import HealthProfile, compute_personalized_scores


st.set_page_config(page_title="Comparateur de produits", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] {display: none;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Comparateur de produits")

st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)

if "compare_selection" not in st.session_state or not st.session_state.compare_selection:
    st.info("Aucun produit sélectionné. Retournez au Dashboard et cochez la case \"Comparer\" sur 2 à 3 produits.")
    st.stop()

codes = [str(c) for c in st.session_state.compare_selection]

if len(codes) < 2:
    st.info("Sélectionnez au moins 2 produits pour comparer.")
    st.stop()

if len(codes) > 3:
    codes = codes[:3]
    st.warning("Seuls les 3 premiers produits sélectionnés sont comparés.")

conn = get_connection()

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

placeholders = ",".join(["%s"] * len(codes))

QUERY = f"""
SELECT p.code_produit AS code,
       p.nom_produit AS product_name,
       p.categorie_principale,
       p.nutrition_grade AS nutriscore_grade,
       p.nova_group,
       v.sugars_100g,
       v.salt_100g,
       v.saturated_fat_100g,
       v.fiber_100g,
       v.proteins_100g
FROM produit p
LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
WHERE p.code_produit IN ({placeholders})
"""

compare_df = pd.read_sql(QUERY, conn, params=tuple(codes))

if compare_df.empty:
    st.error("Impossible de charger les produits sélectionnés.")
    st.stop()

# Calcul éventuel du score personnalisé
health_profile = st.session_state.get("health_profile")
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

cols = st.columns(len(compare_df))

for col, (_, row) in zip(cols, compare_df.iterrows()):
    with col:
        st.subheader(str(row["product_name"]))
        st.caption(f"Code : {row['code']}")
        st.markdown(f"**Catégorie principale :** {row.get('categorie_principale', 'autres')}")
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

# Résultat global : meilleur produit
best_row = None
reason = None

if compare_df["personal_score"].notna().any():
    idx = compare_df["personal_score"].idxmax()
    best_row = compare_df.loc[idx]
    reason = "score santé personnalisé"
else:
    mapping = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}
    nutri_numeric = (
        compare_df["nutriscore_grade"]
        .fillna("")
        .astype(str)
        .str.upper()
        .map(mapping)
        .fillna(0.0)
    )
    if nutri_numeric.max() > 0:
        idx = nutri_numeric.idxmax()
        best_row = compare_df.loc[idx]
        reason = "NutriScore"

if best_row is not None:
    st.subheader("Meilleur choix parmi ces produits")
    st.markdown(
        f"**{best_row['product_name']}** (code {best_row['code']})\n\n"
        f"- Catégorie principale : {best_row.get('categorie_principale', 'autres')}\n"
        f"- NutriScore : {best_row.get('nutriscore_grade', 'N/A')}\n"
        f"- Groupe NOVA : {best_row.get('nova_group', 'N/A')}\n"
        + (
            f"- Score santé personnalisé : {best_row['personal_score']:.2f}\n"
            if pd.notna(best_row.get("personal_score"))
            else ""
        )
    )
    if reason:
        st.caption(f"Meilleur produit déterminé selon : {reason}.")

if st.button("Retour au Dashboard"):
    st.switch_page("main.py")
