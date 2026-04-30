"""Panier favori — schéma v3.

Changements :
- Valeurs nutritionnelles directement dans produit
- Recherche par code_barre OU id_produit::text
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
from image_utils import get_no_image_data_uri
from top_menu import render_top_menu

st.set_page_config(page_title="Mon panier favori", layout="wide", initial_sidebar_state="collapsed")
render_top_menu("Favoris")

st.title("Mon panier favori")
st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)

st.markdown(
    """
    <style>
    div[class*="st-key-remove_fav_"] button {
        min-width:3rem; padding:0.35rem 0.8rem; border-radius:999px;
        font-size:1.3rem; line-height:1;
        border:1px solid rgba(225,29,72,0.55); color:#ffffff;
        background:linear-gradient(135deg,#fb7185,#e11d48);
        box-shadow:0 8px 18px rgba(225,29,72,0.2);
    }
    div[class*="st-key-remove_fav_"] button:hover {
        border-color:rgba(190,24,93,0.75); box-shadow:0 10px 20px rgba(225,29,72,0.24);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "favorites" not in st.session_state or not st.session_state.favorites:
    st.info("Aucun produit dans votre panier favori. Retournez au Dashboard et utilisez le bouton \"Ajouter aux favoris\".")
    st.stop()

codes = [str(c) for c in st.session_state.favorites]

conn = get_connection()
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning)

placeholders = ",".join(["%s"] * len(codes))

QUERY = f"""
SELECT
    p.id_produit,
    COALESCE(p.code_barre, p.id_produit::text) AS code,
    p.nom_produit                               AS product_name,
    p.categorie_principale,
    p.nutrition_grade                           AS nutriscore_grade,
    p.nova_group,
    p.image_url,
    p.sugars_100g,
    p.salt_100g,
    p.saturated_fat_100g,
    p.fiber_100g,
    p.proteins_100g
FROM produit p
WHERE p.code_barre IN ({placeholders})
   OR p.id_produit::text IN ({placeholders})
"""

fav_df = pd.read_sql(QUERY, conn, params=tuple(codes) * 2)
fav_df = fav_df.drop_duplicates(subset=["id_produit"])

if fav_df.empty:
    st.error("Impossible de charger les produits favoris.")
    st.stop()

# Score personnalisé
health_profile     = st.session_state.get("health_profile")
use_health_profile = st.session_state.get("use_health_profile", False)

if use_health_profile and isinstance(health_profile, HealthProfile):
    try:
        scores = compute_personalized_scores(fav_df, health_profile)
        fav_df = fav_df.assign(personal_score=scores)
    except Exception as e:
        st.warning(f"Impossible de calculer le score personnalisé : {e}")
        fav_df["personal_score"] = pd.NA
else:
    fav_df["personal_score"] = pd.NA

st.subheader("Produits de votre panier")

cols = st.columns(2)

for index, (_, row) in enumerate(fav_df.iterrows()):
    col = cols[index % 2]

    image_html = ""
    image_url  = row.get("image_url")
    if pd.notna(image_url) and str(image_url).strip():
        image_html = f'<img src="{image_url}" style="width:100%;height:100%;object-fit:cover;border-radius:8px;" />'
    else:
        no_img = get_no_image_data_uri()
        if no_img:
            image_html = f'<img src="{no_img}" style="width:100%;height:100%;object-fit:cover;border-radius:8px;" />'

    nutriscore_display = row.get("nutriscore_grade", "N/A")
    if pd.isna(nutriscore_display) or not str(nutriscore_display).strip():
        nutriscore_display = "N/A"

    cat = row.get("categorie_principale") or "autres"
    code_str = str(row.get("code", row.get("id_produit", "")))

    with col:
        st.markdown(
            f"""
            <div style="border:1px solid #ddd;padding:15px;border-radius:10px;margin-bottom:15px;
                        background-color:#fafafa;height:260px;display:flex;flex-direction:row;
                        gap:12px;box-sizing:border-box;">
                <div style="flex:0 0 40%;max-width:40%;display:flex;align-items:center;
                            justify-content:center;overflow:hidden;">{image_html}</div>
                <div style="flex:1 1 60%;max-width:60%;overflow:hidden;">
                    <h4 style="margin-top:0;margin-bottom:8px;word-wrap:break-word;">{row['product_name']}</h4>
                    <p style="margin:2px 0;"><b>Code :</b> {code_str}</p>
                    <p style="margin:2px 0;"><b>Catégorie principale :</b> {cat}</p>
                    <p style="margin:2px 0;"><b>NutriScore :</b> {nutriscore_display}</p>
                    <p style="margin:2px 0;">Sucre : {row.get('sugars_100g', 'N/A')} g / 100g</p>
                    <p style="margin:2px 0;">Sel : {row.get('salt_100g', 'N/A')} g / 100g</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if pd.notna(row.get("personal_score")):
            st.markdown(f"Score santé personnalisé : {row['personal_score']:.2f}")

        if st.button("❤️", key=f"remove_fav_{code_str}", help="Retirer des favoris", type="primary"):
            st.session_state.favorites = [c for c in st.session_state.favorites if str(c) != code_str]
            st.rerun()

st.markdown("---")

# ── Meilleur choix ────────────────────────────────────────────────

if fav_df["personal_score"].notna().any():
    best_idx = fav_df["personal_score"].idxmax()
    best_row = fav_df.loc[best_idx]
    st.subheader("Meilleur choix pour vous dans ce panier")
    st.markdown(
        f"**{best_row['product_name']}** (code {best_row.get('code', best_row.get('id_produit', ''))}) "
        f"— Score santé personnalisé : {best_row['personal_score']:.2f}"
    )
elif fav_df["nutriscore_grade"].notna().any():
    mapping = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}
    nutri_numeric = (
        fav_df["nutriscore_grade"].fillna("").astype(str).str.upper()
        .map(mapping).fillna(0.0)
    )
    if nutri_numeric.max() > 0:
        best_idx = nutri_numeric.idxmax()
        best_row = fav_df.loc[best_idx]
        st.subheader("Meilleur choix selon le NutriScore")
        st.markdown(
            f"**{best_row['product_name']}** (code {best_row.get('code', best_row.get('id_produit', ''))}) "
            f"— NutriScore : {best_row['nutriscore_grade']}"
        )
