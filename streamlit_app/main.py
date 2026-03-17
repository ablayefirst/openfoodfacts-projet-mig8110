import os
import math
import random
import warnings

import streamlit as st
import pandas as pd

from db_connection import get_connection
from admin import run_admin


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

# ===== MENU SIDEBAR =====
st.sidebar.title("Menu")
page = st.sidebar.radio("Aller à", ["Dashboard", "Admin"])

# Si admin -> on exécute admin et on stop ici (sinon le dashboard s'affiche aussi)
if page == "Admin":
    run_admin()
    st.stop()

# ==============================
#  DASHBOARD
# ==============================

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

if "page" not in st.session_state:
    st.session_state.page = 1

category_options = ["Toutes"]
try:
    df_categories = pd.read_sql(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(categorie_principale), ''), 'autres') AS categorie_principale
        FROM produit
        ORDER BY 1
        """,
        conn,
    )
    if not df_categories.empty:
        values = (
            df_categories["categorie_principale"]
            .dropna()
            .astype(str)
            .str.strip()
            .loc[lambda s: s != ""]
            .unique()
            .tolist()
        )
        category_options.extend(values)
except Exception:
    pass

# ==============================
#  BARRE DE RECHERCHE
# ==============================

col1, col2, col3 = st.columns(3)

with col1:
    search_name = st.text_input("Rechercher par nom")

with col2:
    selected_main_category = st.selectbox(
        "Catégorie principale (exacte)",
        options=category_options,
        index=0,
    )

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

category_detail_filter = st.text_input("Recherche libre dans catégories détaillées (optionnel)")

# ==============================
#  RESET PAGINATION SI FILTRES CHANGENT
# ==============================
current_filters_signature = (
    search_name,
    selected_main_category,
    float(max_sugar),
    tuple(nutriscore_filter),
    sort_option,
    sort_order,
    category_detail_filter,
)

if "last_filters_signature" not in st.session_state:
    st.session_state["last_filters_signature"] = current_filters_signature
else:
    if st.session_state["last_filters_signature"] != current_filters_signature:
        st.session_state.page = 1
        st.session_state.home_selection = None
        st.session_state["last_filters_signature"] = current_filters_signature

# ==============================
#  REQUÊTE SQL DYNAMIQUE
# ==============================

query = """
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
       v.proteins_100g,
       COALESCE(string_agg(DISTINCT c.categorie, ', '), 'Non spécifiée') AS categories
FROM produit p
LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
LEFT JOIN produit_categorie pc ON p.code_produit = pc.code_produit
LEFT JOIN categorie c ON pc.id_categorie = c.id_categorie
WHERE 1=1
"""

if search_name:
    query += " AND LOWER(p.nom_produit) LIKE LOWER(%(search_name)s)"

query_params = {"max_sugar": float(max_sugar)}

if search_name:
    query_params["search_name"] = f"%{search_name}%"

if selected_main_category != "Toutes":
    query += """
    AND LOWER(COALESCE(NULLIF(TRIM(p.categorie_principale), ''), 'autres')) = LOWER(%(category_exact)s)
    """
    query_params["category_exact"] = selected_main_category

if category_detail_filter:
    query += """
    AND EXISTS (
        SELECT 1
        FROM produit_categorie pc2
        JOIN categorie c2 ON pc2.id_categorie = c2.id_categorie
        WHERE pc2.code_produit = p.code_produit
          AND LOWER(c2.categorie) LIKE LOWER(%(category_detail_filter)s)
    )
    """
    query_params["category_detail_filter"] = f"%{category_detail_filter}%"

# Filtre sucre : compatible avec les produits sans ligne nutritionnelle
query += " AND (v.sugars_100g IS NULL OR v.sugars_100g <= %(max_sugar)s)"

query += """
GROUP BY p.code_produit,
         p.nom_produit,
         p.categorie_principale,
         p.nutrition_grade,
         p.nova_group,
         p.image_url,
         v.sugars_100g,
         v.salt_100g,
         v.saturated_fat_100g,
         v.fiber_100g,
         v.proteins_100g
"""

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

try:
    df = pd.read_sql(query, conn, params=query_params)
except Exception as e:
    st.error(f"Erreur lors du chargement des produits : {e}")
    df = pd.DataFrame(
        columns=[
            "code",
            "product_name",
            "categorie_principale",
            "nutriscore_grade",
            "nova_group",
            "image_url",
            "sugars_100g",
            "salt_100g",
            "saturated_fat_100g",
            "fiber_100g",
            "proteins_100g",
            "categories",
        ]
    )

if "sugars_100g" not in df.columns:
    df["sugars_100g"] = pd.NA
if "salt_100g" not in df.columns:
    df["salt_100g"] = pd.NA
if "nutriscore_grade" not in df.columns:
    df["nutriscore_grade"] = pd.NA
if "image_url" not in df.columns:
    df["image_url"] = pd.NA
if "categories" not in df.columns:
    df["categories"] = "Non spécifiée"

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
    df = (
        df.assign(_nutri_rank=nutri_rank)
        .sort_values(by="_nutri_rank", ascending=ascending)
        .drop(columns="_nutri_rank")
    )
elif sort_option == "Sucre (g/100g)":
    df = df.sort_values(by="sugars_clean", ascending=ascending, na_position="last")
elif sort_option == "Sel (g/100g)":
    df = df.sort_values(by="salt_clean", ascending=ascending, na_position="last")

# ==============================
#  PAGINATION
# ==============================
# Vue d'accueil par défaut ? (aucune recherche, aucun filtre, sucre par défaut)
is_home = (
    (not search_name)
    and (selected_main_category == "Toutes")
    and (not category_detail_filter)
    and max_sugar == 50.0
)

if is_home:
    if st.session_state.home_selection is None:
        if df.empty:
            st.session_state.home_selection = df.copy()
        else:
            mask_img = df["image_url"].notna() & df["image_url"].astype(str).str.strip().ne("")
            df_with_img = df[mask_img]

            if len(df_with_img) >= 10:
                selection = df_with_img.sample(10, random_state=random.randint(0, 1_000_000))
            else:
                df_without_img = df[~mask_img]
                needed = max(0, 10 - len(df_with_img))
                extras = pd.DataFrame()
                if needed > 0 and len(df_without_img) > 0:
                    extras = df_without_img.sample(
                        min(needed, len(df_without_img)),
                        random_state=random.randint(0, 1_000_000),
                    )
                selection = pd.concat([df_with_img, extras]).head(10)

            st.session_state.home_selection = selection.reset_index(drop=True)

    df_page = st.session_state.home_selection.copy()
    items_per_page = len(df_page)
    total_pages = 1
    st.session_state.page = 1
else:
    st.session_state.home_selection = None

    items_per_page = 10

    total_pages = max(1, (len(df) + items_per_page - 1) // items_per_page)

    if st.session_state.page > total_pages:
        st.session_state.page = total_pages

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

    # Limiter le nombre de catégories affichées (max 3)
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
        categorie_principale_display = row.get("categorie_principale", "autres")
        if pd.isna(categorie_principale_display) or str(categorie_principale_display).strip() == "":
            categorie_principale_display = "autres"

        product_name_display = row.get("product_name", "")
        if pd.isna(product_name_display):
            product_name_display = ""

        nutriscore_display = row.get("nutriscore_grade", "N/A")
        if pd.isna(nutriscore_display) or str(nutriscore_display).strip() == "":
            nutriscore_display = "N/A"

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
                        <span>{product_name_display}</span>{badge_html}</h4>
                    <p style="margin:2px 0;"><b>Catégorie principale:</b> {categorie_principale_display}</p>
                    <p style="margin:2px 0;"><b>Catégories détaillées:</b> {categories_display}</p>
                    <p style="margin:2px 0;"><b>NutriScore:</b> {nutriscore_display}</p>
                    <p style="margin:2px 0;">Sucre: {format_grams(clean_nutrient_value(row['sugars_100g'], 50.0))}</p>
                    <p style="margin:2px 0;">Sel: {format_grams(clean_nutrient_value(row['salt_100g'], 25.0))}</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        # Bouton de détail à l'intérieur de la carte
        if st.button("Détails", key=f"detail_{row['code']}"):
            st.session_state.selected_code = str(row["code"])
            try:
                st.query_params["code"] = str(row["code"])
            except AttributeError:
                st.experimental_set_query_params(code=str(row["code"]))

            try:
                st.switch_page("pages/01_detail_produit.py")
            except Exception:
                st.info("Veuillez ouvrir la page 'Détail du produit' via le menu latéral.")

# ==============================
# ⬅️ ➡️ BOUTONS PAGINATION (sauf accueil aléatoire)
# ==============================

if not is_home:
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if st.button("⬅️ Page précédente") and st.session_state.page > 1:
            st.session_state.page -= 1
            st.rerun()

    with col3:
        if st.button("Page suivante ➡️") and st.session_state.page < total_pages:
            st.session_state.page += 1
            st.rerun()

    st.write(f"Page {st.session_state.page} / {total_pages}")

# (Optionnel mais propre) : fermer la connexion
try:
    conn.close()
except Exception:
    pass