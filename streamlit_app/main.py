import os
import random

import streamlit as st
import pandas as pd
import warnings
from db_connection import get_connection


def clean_nutrient_series(series: pd.Series, max_reasonable: float) -> pd.Series:
    return series.apply(lambda v: clean_nutrient_value(v, max_reasonable))


def clean_nutrient_value(value, max_reasonable: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("nan")

    if numeric > (max_reasonable * 10):
        numeric = numeric / 100.0

    if numeric < 0 or numeric > max_reasonable:
        return float("nan")

    return numeric


def format_grams(value: float) -> str:
    if pd.isna(value):
        return "Non applicable"
    return f"{value:.2f} g"


def shorten_text(text: str, max_length: int = 30) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"

st.set_page_config(page_title="Santé & Nutrition", layout="wide")

# Titre avec logo sur la même ligne
title_col1, title_col2 = st.columns([0.15, 0.85])
with title_col1:
    # Logo local, chemin basé sur l'emplacement de ce fichier
    logo_path = os.path.join(os.path.dirname(__file__), "static", "logo", "logo_V2.png")
    st.image(logo_path, width=100)
with title_col2:
    # Utilisation de markdown pour mieux contrôler l'alignement horizontal
    st.markdown(
        "<h1 style='margin-top: -10px; margin-bottom: 0;'>Application Santé & Nutrition</h1>",
        unsafe_allow_html=True,
    )

conn = get_connection()

if "selected_code" not in st.session_state:
    st.session_state.selected_code = None

if "home_selection" not in st.session_state:
    st.session_state.home_selection = None

# ==============================
#  BARRE DE RECHERCHE
# ==============================

col1, col2, col3 = st.columns(3)

with col1:
    search_name = st.text_input("Rechercher par nom")

with col2:
    category_filter = st.text_input("Filtrer par catégorie")

with col3:
    max_sugar = st.number_input("Sucre max (g/100g)", min_value=0.0, value=50.0)

col4, col5, col6 = st.columns(3)

nutriscore_options = ["A", "B", "C", "D", "E"]

with col4:
    nutriscore_filter = st.multiselect(
        "Filtrer NutriScore",
        options=nutriscore_options,
        default=nutriscore_options,
    )

with col5:
    sort_option = st.selectbox(
        "Trier par",
        [
            "NutriScore (A→E)",
            "Sucre (g/100g)",
            "Sel (g/100g)",
        ],
    )

with col6:
    sort_order = st.radio(
        "Ordre",
        ("Croissant", "Décroissant"),
        horizontal=True,
    )

# ==============================
#  REQUÊTE SQL DYNAMIQUE
# ==============================

query = """
SELECT p.code_produit AS code,
       p.nom_produit AS product_name,
       p.nutrition_grade AS nutriscore_grade,
       p.nova_group,
    p.image_url,
       v.sugars_100g,
       v.salt_100g,
       v.saturated_fat_100g,
       v.fiber_100g,
       v.proteins_100g,
       COALESCE(string_agg(DISTINCT c.categorie, ', '), 'Non spécifiée') AS categories
FROM produit p
JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
LEFT JOIN produit_categorie pc ON p.code_produit = pc.code_produit
LEFT JOIN categorie c ON pc.id_categorie = c.id_categorie
WHERE 1=1
"""

if search_name:
	query += f" AND LOWER(p.nom_produit) LIKE LOWER('%{search_name}%')"

if category_filter:
	query += f" AND LOWER(c.categorie) LIKE LOWER('%{category_filter}%')"

# Filtre sucre
query += f" AND v.sugars_100g <= {max_sugar}"

query += "\nGROUP BY p.code_produit, p.nom_produit, p.nutrition_grade, p.nova_group, v.sugars_100g, v.salt_100g, v.saturated_fat_100g, v.fiber_100g, v.proteins_100g"

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)
df = pd.read_sql(query, conn)

df["sugars_clean"] = clean_nutrient_series(df["sugars_100g"], 50.0)
df["salt_clean"] = clean_nutrient_series(df["salt_100g"], 25.0)

nutri_series = df["nutriscore_grade"].fillna("").astype(str).str.upper()

if nutriscore_filter:
    df = df[nutri_series.isin(nutriscore_filter)]
    nutri_series = nutri_series.loc[df.index]
else:
    df = df.iloc[0:0]
    nutri_series = nutri_series.iloc[0:0]

ascending = sort_order == "Croissant"

if sort_option == "NutriScore (A→E)":
    order_map = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    nutri_rank = nutri_series.map(order_map).fillna(99)
    df = df.assign(_nutri_rank=nutri_rank).sort_values(
        by="_nutri_rank", ascending=ascending
    ).drop(columns="_nutri_rank")
elif sort_option == "Sucre (g/100g)":
    df = df.sort_values(by="sugars_clean", ascending=ascending)
elif sort_option == "Sel (g/100g)":
    df = df.sort_values(by="salt_clean", ascending=ascending)

# ==============================
#  PAGINATION
# ==============================
# Vue d'accueil par défaut ? (aucune recherche, aucun filtre, sucre par défaut)
is_home = (
    (not search_name)
    and (not category_filter)
    and max_sugar == 50.0
)

if is_home:
    if st.session_state.home_selection is None:
        mask_img = df["image_url"].notna() & df["image_url"].astype(str).str.strip().ne("")
        df_with_img = df[mask_img]

        if len(df_with_img) >= 10:
            selection = df_with_img.sample(10, random_state=random.randint(0, 1_000_000))
        else:
            df_without_img = df[~mask_img]
            needed = max(0, 10 - len(df_with_img))
            extras = pd.DataFrame()
            if needed > 0 and len(df_without_img) > 0:
                extras = df_without_img.sample(min(needed, len(df_without_img)), random_state=random.randint(0, 1_000_000))
            selection = pd.concat([df_with_img, extras]).head(10)

        st.session_state.home_selection = selection.reset_index(drop=True)

    df_page = st.session_state.home_selection.copy()
    items_per_page = len(df_page)
    total_pages = 1
    st.session_state.page = 1
else:
    st.session_state.home_selection = None

    items_per_page = 10

    if "page" not in st.session_state:
        st.session_state.page = 1

    total_pages = max(1, (len(df) // items_per_page) + 1)

    start = (st.session_state.page - 1) * items_per_page
    end = start + items_per_page

    df_page = df.iloc[start:end]

# ==============================
#  AFFICHAGE EN CARTES
# ==============================

st.subheader(f"Résultats ({len(df)} produits trouvés)")



# 2 cartes par ligne
cols = st.columns(2)

for index, row in df_page.iterrows():
    col = cols[index % 2]

    # Limiter le nombre de catégories affichées (max 5)
    categories_display = row.get("categories", "Non spécifiée")
    if pd.notna(categories_display) and categories_display != "Non spécifiée":
        cats_list = [shorten_text(c.strip()) for c in str(categories_display).split(",") if c.strip()]
        if len(cats_list) > 3:
            categories_display = ", ".join(cats_list[:3]) + " ..."
        else:
            categories_display = ", ".join(cats_list)

    # Image du produit (si disponible)
    image_html = ""
    if pd.notna(row.get("image_url")) and str(row.get("image_url")).strip() != "":
        image_html = f'<img src="{row["image_url"]}" style="width:100%; height:100%; object-fit:cover; border-radius:8px;" />'

    grade_upper = (row.get("nutriscore_grade") or "").upper()
    badge_html = ""
    if grade_upper in ("A", "B"):
        badge_html = "<span style=\"background-color:#0f9d58; color:white; padding:2px 8px; border-radius:12px; font-size:12px; margin-left:6px;\">Top choix</span>"

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
                    <h4 style="margin-top:0; margin-bottom:8px; word-wrap:break-word; display:flex; align-items:center; gap:6px;">
                        <span>{row['product_name']}</span>{badge_html}</h4>   
                    <p style="margin:2px 0;"><b>Catégorie:</b> {categories_display}</p>
                    <p style="margin:2px 0;"><b>NutriScore:</b> {row['nutriscore_grade'] or 'N/A'}</p>
                    <p style="margin:2px 0;">Sucre: {format_grams(clean_nutrient_value(row['sugars_100g'], 50.0))}</p>
                    <p style="margin:2px 0;">Sel: {format_grams(clean_nutrient_value(row['salt_100g'], 25.0))}</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        # Bouton de détail à l'intérieur de la carte (sans emoji)
        if st.button("Détails", key=f"detail_{row['code']}"):
            st.session_state.selected_code = int(row["code"])
            try:
                st.query_params["code"] = str(row["code"])
            except AttributeError:
                st.experimental_set_query_params(code=row["code"])

            try:
                st.switch_page("pages/01_detail_produit.py")
            except Exception:
                st.info("Veuillez ouvrir la page 'Détail du produit' via le menu latéral.")

# ==============================
# ⬅️ ➡️ BOUTONS PAGINATION (sauf accueil aléatoire)
# ==============================

if not is_home:
    col1, col2, col3 = st.columns([1,2,1])

    with col1:
        if st.button("⬅️ Page précédente") and st.session_state.page > 1:
            st.session_state.page -= 1

    with col3:
        if st.button("Page suivante ➡️") and st.session_state.page < total_pages:
            st.session_state.page += 1

    st.write(f"Page {st.session_state.page} / {total_pages}")
