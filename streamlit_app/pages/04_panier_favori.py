import sys
import warnings
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection
from image_utils import get_no_image_data_uri
from top_menu import render_top_menu
from ui_hero import render_page_hero


st.set_page_config(page_title="Mon panier favori", layout="wide", initial_sidebar_state="collapsed")

render_top_menu("Favoris")

st.markdown(
    """
    <style>
    div[class*="st-key-open_card_"] button {
        border-radius: 12px;
        font-weight: 700;
        color: #0f172a;
        border-color: rgba(15, 118, 110, 0.55);
        background:
            linear-gradient(135deg, rgba(20, 184, 166, 0.35), rgba(245, 158, 11, 0.3)),
            #ffffff;
        box-shadow: 0 4px 14px rgba(15, 118, 110, 0.2);
    }

    div[class*="st-key-open_card_"] button:hover {
        border-color: rgba(15, 118, 110, 0.8);
        box-shadow: 0 6px 16px rgba(15, 118, 110, 0.26);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

render_page_hero(
    kicker="Panier personnel",
    title="Mon panier favori",
    subtitle="Retrouvez vos produits enregistres et accedez rapidement a leur fiche detail.",
)

if "favorites" not in st.session_state or not st.session_state.favorites:
    st.info("Aucun produit dans votre panier favori. Retournez au Dashboard et utilisez le bouton \"Ajouter aux favoris\".")
    st.stop()

codes = [str(c) for c in st.session_state.favorites]

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
       p.image_url,
       v.sugars_100g,
       v.salt_100g,
       v.saturated_fat_100g,
       v.fiber_100g,
       v.proteins_100g
FROM produit p
LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
WHERE p.code_produit IN ({placeholders})
"""

fav_df = pd.read_sql(QUERY, conn, params=tuple(codes))

if fav_df.empty:
    st.error("Impossible de charger les produits favoris.")
    st.stop()


st.markdown("---")
# Affichage en cartes avec photo (2 cartes par ligne)
cols = st.columns(2)

for index, (_, row) in enumerate(fav_df.iterrows()):
    col = cols[index % 2]
    code_str = str(row["code"])

    image_html = ""
    image_url = row.get("image_url")
    if pd.notna(image_url) and str(image_url).strip() != "":
        image_html = f'<img src="{image_url}" style="width:100%; height:100%; object-fit:cover; border-radius:8px;" />'
    else:
        no_image_data = get_no_image_data_uri()
        if no_image_data:
            image_html = f'<img src="{no_image_data}" style="width:100%; height:100%; object-fit:cover; border-radius:8px;" />'

    nutriscore_display = row.get("nutriscore_grade", "N/A")
    if pd.isna(nutriscore_display) or str(nutriscore_display).strip() == "":
        nutriscore_display = "N/A"

    with col:

        st.markdown(
            f"""
            <div style="
                border:1px solid #ddd;
                padding:15px;
                border-radius:10px;
                margin-bottom:15px;
                background-color:#fafafa;
                height:260px;
                display:flex;
                flex-direction:row;
                gap:12px;
                box-sizing:border-box;
            ">
                <div style="flex:0 0 40%; max-width:40%; display:flex; align-items:center; justify-content:center; overflow:hidden;">
                    {image_html}
                </div>
                <div style="flex:1 1 60%; max-width:60%; overflow:hidden;">
                    <h4 style="margin-top:0; margin-bottom:8px; word-wrap:break-word;">
                        {row['product_name']}
                    </h4>
                    <p style="margin:2px 0;"><b>Code :</b> {row['code']}</p>
                    <p style="margin:2px 0;"><b>Catégorie principale :</b> {row.get('categorie_principale', 'autres')}</p>
                    <p style="margin:2px 0;"><b>NutriScore :</b> {nutriscore_display}</p>
                    <p style="margin:2px 0;">Sucre : {row.get('sugars_100g', 'N/A')} g / 100g</p>
                    <p style="margin:2px 0;">Sel : {row.get('salt_100g', 'N/A')} g / 100g</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button(
            "Détail",
            key=f"open_card_{code_str}",
            help="Voir le détail du produit",
            use_container_width=True,
        ):
            st.session_state.selected_code = code_str
            try:
                st.query_params["code"] = code_str
            except AttributeError:
                st.experimental_set_query_params(code=code_str)

            try:
                st.switch_page("pages/01_detail_produit.py")
            except Exception:
                st.info("Veuillez ouvrir la page 'Détail du produit' via le menu latéral.")
