"""Page principale Streamlit : tableau de bord Santé & Nutrition.

Ce module gère :
- la navigation vers les autres pages (tendances, profil santé, favoris, admin),
- la barre de recherche et tous les filtres disponibles,
- la construction de la requête SQL vers PostgreSQL,
- la préparation des données (nettoyage sucre / sel, NutriScore, etc.),
- l'application éventuelle du profil santé (tri + filtrage),
- la pagination des résultats,
- l'affichage des cartes produits avec actions (détail, comparaison, favoris).
"""

import os
import math
import random
import sys
import warnings
from pathlib import Path

import streamlit as st
import pandas as pd

# Ensure local Streamlit modules are importable regardless of launch directory.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection
from top_menu import render_top_menu
from image_utils import get_no_image_data_uri


def clean_nutrient_series(series: pd.Series, max_reasonable: float) -> pd.Series:
    """Nettoie une série de valeurs nutritionnelles (ex. sucre, sel).

    - `series` contient les valeurs brutes lues depuis la base (peuvent être str, None, etc.).
    - `max_reasonable` sert à définir une borne haute réaliste (au-delà on considère la donnée invalide).
    - On applique clean_nutrient_value valeur par valeur et on renvoie une nouvelle série numérique.
    """
    return series.apply(lambda v: clean_nutrient_value(v, max_reasonable))


def clean_nutrient_value(value, max_reasonable: float) -> float:
    """Convertit une valeur nutritionnelle brute en float nettoyé.

    Étapes :
    - Tentative de conversion en float ; en cas d'échec → NaN.
    - Correction de certaines valeurs visiblement en mg (très grandes → division par 100).
    - Rejet des valeurs négatives ou supérieures à `max_reasonable` → NaN.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("nan")

    if numeric > (max_reasonable * 10):
        numeric = numeric / 100.0

    # On écarte les valeurs négatives ou beaucoup trop élevées
    if numeric < 0 or numeric > max_reasonable:
        return float("nan")

    return numeric


def format_grams(value: float) -> str:
    """Formate une quantité en grammes pour l'affichage dans les cartes.

    - Si la valeur est NaN → renvoie "Non applicable".
    - Sinon, affiche avec 2 décimales et l'unité "g".
    """
    if pd.isna(value):
        return "Non applicable"
    return f"{value:.2f} g"


def shorten_text(text: str, max_length: int = 30) -> str:
    """Raccourcit un texte long pour ne pas casser la mise en page.

    - Si `text` est plus court que `max_length`, on le renvoie tel quel.
    - Sinon, on tronque et on ajoute un caractère de suspension.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


########################################
# CONFIGURATION GLOBALE DE LA PAGE
########################################

# Configuration de base de la page Streamlit (titre de l'onglet, largeur, etc.)
st.set_page_config(page_title="Santé & Nutrition", layout="wide", initial_sidebar_state="collapsed")

########################################
# NAVIGATION PRINCIPALE (MENU HORIZONTAL)
########################################

render_top_menu("Dashboard")

########################################
# CONNEXION BD & ÉTAT DE SESSION
########################################

# Connexion à la base PostgreSQL (fermée à la fin du script)
conn = get_connection()

if "selected_code" not in st.session_state:
    # Code du produit actuellement sélectionné pour la page de détail
    st.session_state.selected_code = None

if "home_selection" not in st.session_state:
    # Échantillon de produits pour la page d'accueil (cas "is_home")
    st.session_state.home_selection = None

if "page" not in st.session_state:
    # Index de la page courante de pagination (1-based)
    st.session_state.page = 1

if "compare_selection" not in st.session_state:
    # Liste des codes produits sélectionnés pour la comparaison (max 4)
    st.session_state.compare_selection = []

if "favorites" not in st.session_state:
    # Liste des codes produits marqués comme favoris (panier santé)
    st.session_state.favorites = []

########################################
# RÉCUPÉRATION DES CATÉGORIES PRINCIPALES
########################################

category_options = ["Toutes"]
try:
    df_categories = pd.read_sql(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(categorie_principale), ''), 'autres') AS categorie_principale
        FROM produit
        WHERE categorie_principale IS NULL
           OR (
                TRIM(categorie_principale) NOT LIKE '[%'
            AND POSITION(E'\n' IN categorie_principale) = 0
           )
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
    # En cas d'erreur sur la requête de catégories, on garde juste "Toutes"
    pass

########################################
# BARRE DE RECHERCHE & FILTRES PRINCIPAUX
########################################
st.markdown("---")
col1, col2, col3, col4 = st.columns([1.2, 1, 1, 0.9])

st.markdown(
    """
    <style>
    div[class*="st-key-fav_"] button {
        min-width: 3rem;
        padding: 0.35rem 0.8rem;
        border-radius: 999px;
        font-size: 1.3rem;
        line-height: 1;
        border: 1px solid rgba(225, 29, 72, 0.22);
        color: #e11d48;
        background: rgba(255, 241, 242, 0.96);
        box-shadow: 0 4px 10px rgba(225, 29, 72, 0.08);
    }

    div[class*="st-key-fav_"] button[kind="primary"] {
        border: 1px solid rgba(225, 29, 72, 0.22);
        color: #e11d48;
        background: rgba(255, 241, 242, 0.96);
        box-shadow: 0 4px 10px rgba(225, 29, 72, 0.08);
    }

    div[class*="st-key-fav_"] button:hover {
        border-color: rgba(225, 29, 72, 0.5);
        box-shadow: 0 8px 18px rgba(225, 29, 72, 0.16);
    }

    div[class*="st-key-compare_"] button {
        min-width: 3rem;
        padding: 0.35rem 0.8rem;
        border-radius: 999px;
        font-size: 0.95rem;
        line-height: 1;
    }

    div[class*="st-key-compare_"] button[kind="primary"] {
        border-color: rgba(37, 99, 235, 0.5);
        background: linear-gradient(135deg, #60a5fa, #2563eb);
        color: #ffffff;
        box-shadow: 0 8px 18px rgba(37, 99, 235, 0.2);
    }

    </style>
    """,
    unsafe_allow_html=True,
)

with col1:
    # Recherche texte sur le nom du produit
    search_name = st.text_input("Rechercher par nom")

with col2:
    search_code = st.text_input("Code produit / code-barres")

with col3:
    # Filtre sur la catégorie principale (valeur exacte parmi les catégories connues)
    selected_main_category = st.selectbox(
        "Catégorie principale (exacte)",
        options=category_options,
        index=0,
    )

with col4:
    # Filtre quantitatif sur le sucre (borne haute en g/100g)
    max_sugar = st.number_input("Sucre max (g/100g)", min_value=0.0, value=50.0)

col4, col5, col6 = st.columns(3)

nutriscore_options = ["A", "B", "C", "D", "E"]

with col4:
    # Filtre multiple sur les grades NutriScore autorisés
    nutriscore_filter = st.multiselect(
        "Filtrer NutriScore",
        options=nutriscore_options,
        default=nutriscore_options,
    )

with col5:
    # Choix du critère de tri principal (avant le tri personnalisé éventuel)
    sort_option = st.selectbox(
        "Trier par",
        [
            "NutriScore (A→E)",
            "Sucre (g/100g)",
            "Sel (g/100g)",
        ],
    )

with col6:
    # Ordre de tri (croissant / décroissant)
    sort_order = st.radio(
        "Ordre",
        ("Croissant", "Décroissant"),
        horizontal=True,
    )

category_detail_filter = st.text_input(
    "Recherche libre dans catégories détaillées (optionnel)"
)

search_ingredient = st.text_input(
    "Rechercher par ingrédient (synonymes inclus)",
    placeholder="ex: egg, sucre, farine…",
)

# ==============================
#  RESET PAGINATION SI FILTRES CHANGENT
# ==============================
current_filters_signature = (
    search_name,
    search_code,
    selected_main_category,
    float(max_sugar),
    tuple(nutriscore_filter),
    sort_option,
    sort_order,
    category_detail_filter,
    search_ingredient,
)

if "last_filters_signature" not in st.session_state:
    # Première exécution : on mémorise simplement la signature courante
    st.session_state["last_filters_signature"] = current_filters_signature
else:
    # Si un des filtres, du tri ou du profil santé change, on remet la pagination à 1
    # et on invalide la sélection "home" (pour la recalculer).
    if st.session_state["last_filters_signature"] != current_filters_signature:
        st.session_state.page = 1
        st.session_state.home_selection = None
        st.session_state["last_filters_signature"] = current_filters_signature

########################################
# CONSTRUCTION DE LA REQUÊTE SQL DYNAMIQUE
########################################

# Requête principale : on assemble progressivement les filtres en fonction
# de ce que l'utilisateur saisit dans l'interface.
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
    # Filtre textuel sur le nom du produit (LIKE insensible à la casse)
    query += " AND LOWER(p.nom_produit) LIKE LOWER(%(search_name)s)"

if search_code:
    query += " AND p.code_produit LIKE %(search_code)s"

query_params = {"max_sugar": float(max_sugar)}

if search_name:
    query_params["search_name"] = f"%{search_name}%"

if search_code:
    query_params["search_code"] = f"%{search_code.strip()}%"

if selected_main_category != "Toutes":
    # Filtre exact sur la catégorie principale (avec gestion des valeurs vides → 'autres')
    query += """
    AND LOWER(COALESCE(NULLIF(TRIM(p.categorie_principale), ''), 'autres')) = LOWER(%(category_exact)s)
    """
    query_params["category_exact"] = selected_main_category

if category_detail_filter:
    # Filtre texte sur les catégories détaillées, en utilisant une sous-requête EXISTS
    # pour ne garder que les produits ayant au moins une catégorie correspondante.
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

if search_ingredient:
    # Passe par ingredient_lookup pour chercher via les synonymes et formes canoniques.
    # Exemple : "egg" trouve aussi les produits contenant "oeuf" si le synonyme existe.
    query += """
    AND EXISTS (
        SELECT 1
        FROM produit_ingredient pi2
        JOIN ingredient i2 ON i2.id_ingredient = pi2.id_ingredient
        JOIN ingredient_lookup il_raw
          ON il_raw.nom_recherche_normalise = LOWER(TRIM(i2.ingredients_nom))
        JOIN ingredient_lookup il_search
          ON il_search.nom_canonique = il_raw.nom_canonique
        WHERE pi2.code_produit = p.code_produit
          AND il_search.nom_recherche_normalise LIKE %(search_ingredient)s
    )
    """
    query_params["search_ingredient"] = f"%{search_ingredient.strip().lower()}%"

# Filtre sucre côté base :
# - On accepte les produits sans infos nutritionnelles (v.sugars_100g IS NULL)
# - Ou ceux dont le sucre est <= max_sugar.
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
    # Lecture du résultat SQL dans un DataFrame pandas
    df = pd.read_sql(query, conn, params=query_params)
except Exception as e:
    # En cas d'erreur, on affiche un message et on travaille avec un DF vide mais typé
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

# On s'assure que toutes les colonnes attendues existent, même si la requête a renvoyé
# un sous-ensemble de colonnes.
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

# Création de colonnes numériques nettoyées pour le sucre et le sel
df["sugars_clean"] = clean_nutrient_series(df["sugars_100g"], 50.0)
df["salt_clean"] = clean_nutrient_series(df["salt_100g"], 25.0)

nutri_series = df["nutriscore_grade"].fillna("").astype(str).str.upper()

# Application du filtre NutriScore : ne garder que les lignes dont le grade
# est dans la liste sélectionnée. Si aucun grade sélectionné, on vide le DF.
if nutriscore_filter:
    df = df[nutri_series.isin(nutriscore_filter)]
    nutri_series = nutri_series.loc[df.index]
else:
    df = df.iloc[0:0]
    nutri_series = nutri_series.iloc[0:0]

# Préparation du sens du tri (croissant / décroissant)
ascending = sort_order == "Croissant"

if sort_option == "NutriScore (A→E)":
    # On mappe les lettres A→E sur un rang numérique pour pouvoir trier facilement.
    order_map = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    nutri_rank = nutri_series.map(order_map).fillna(99)
    df = (
        df.assign(_nutri_rank=nutri_rank)
        .sort_values(by="_nutri_rank", ascending=ascending)
        .drop(columns="_nutri_rank")
    )
elif sort_option == "Sucre (g/100g)":
    # Tri direct sur la colonne nettoyée du sucre
    df = df.sort_values(by="sugars_clean", ascending=ascending, na_position="last")
elif sort_option == "Sel (g/100g)":
    # Tri direct sur la colonne nettoyée du sel
    df = df.sort_values(by="salt_clean", ascending=ascending, na_position="last")

########################################
# PAGINATION & VUE D'ACCUEIL
########################################

# Vue d'accueil par défaut ? (aucune recherche, aucun filtre texte/catégorie,
# sucre par défaut). Dans ce cas, on affiche un petit échantillon.
is_home = (
    (not search_name)
    and (not search_code)
    and (selected_main_category == "Toutes")
    and (not category_detail_filter)
    and (not search_ingredient)
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

    # Cas général : on pagine sur le DataFrame `df` TEL QU'IL EST après
    # tous les filtres (recherche, catégories, NutriScore, sucre, profil santé, etc.).
    items_per_page = 10

    total_pages = max(1, (len(df) + items_per_page - 1) // items_per_page)

    if st.session_state.page > total_pages:
        st.session_state.page = total_pages

    start = (st.session_state.page - 1) * items_per_page
    end = start + items_per_page

    df_page = df.iloc[start:end]

########################################
# AFFICHAGE EN CARTES (LISTE DES PRODUITS)
########################################

# IMPORTANT : `len(df)` représente ici le nombre de produits RESTANTS après
# l'ensemble des filtres appliqués :
# - filtres de la barre de recherche (nom, catégorie, sucre, NutriScore, etc.),
# - filtre texte sur les catégories détaillées,
# - filtrage supplémentaire lié au profil santé (seuils sucre / sel).
st.subheader(f"Résultats ({len(df)} produits trouvés)")

selected_codes = st.session_state.compare_selection
if selected_codes:
    st.caption(f"Produits sélectionnés pour comparaison : {len(selected_codes)}")
    if st.button("Comparer les produits sélectionnés"):
        if len(selected_codes) < 2:
            st.warning("Sélectionnez au moins 2 produits pour comparer.")
        else:
            try:
                st.switch_page("pages/03_comparateur_produits.py")
            except Exception:
                st.info("Ouvrez la page 'Comparateur de produits' via le menu latéral.")

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

    # Image du produit (si disponible), sinon image par défaut
    image_html = ""
    image_url = row.get("image_url")
    if pd.notna(image_url) and str(image_url).strip() != "":
        image_html = f'<img src="{image_url}" style="width:100%; height:100%; object-fit:cover; border-radius:8px;" />'
    else:
        no_image_data = get_no_image_data_uri()
        if no_image_data:
            image_html = f'<img src="{no_image_data}" style="width:100%; height:100%; object-fit:cover; border-radius:8px;" />'

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
        code_str = str(row["code"])

        action_col1, action_col2, action_col3 = st.columns([1.2, 1.1, 0.7])

        # Bouton de detail dans la meme ligne d'actions
        with action_col1:
            if st.button("Détails", key=f"detail_{code_str}", use_container_width=True):
                st.session_state.selected_code = code_str
                try:
                    st.query_params["code"] = code_str
                except AttributeError:
                    st.experimental_set_query_params(code=code_str)

                try:
                    st.switch_page("pages/01_detail_produit.py")
                except Exception:
                    st.info("Veuillez ouvrir la page 'Détail du produit' via le menu latéral.")

        # Bouton sticker pour selectionner le produit dans le comparateur, sur la meme ligne
        compare_selected = code_str in st.session_state.compare_selection
        with action_col2:
            compare_label = "⚖️ Compare" if not compare_selected else "✅ Compare"
            compare_help = "Ajouter a la comparaison" if not compare_selected else "Retirer de la comparaison"
            if st.button(
                compare_label,
                key=f"compare_{code_str}",
                help=compare_help,
                type="primary" if compare_selected else "secondary",
                use_container_width=True,
            ):
                if compare_selected:
                    st.session_state.compare_selection = [
                        c for c in st.session_state.compare_selection if c != code_str
                    ]
                else:
                    if len(st.session_state.compare_selection) >= 4:
                        st.info("Vous ne pouvez comparer que 4 produits à la fois. Décochez un produit avant d'en ajouter un autre.")
                    else:
                        st.session_state.compare_selection.append(code_str)
                st.rerun()

        # Bouton favori au format coeur, sur la meme ligne d'actions
        is_favorite = code_str in st.session_state.favorites
        fav_label = "❤️" if is_favorite else "♡"
        fav_help = "Retirer des favoris" if is_favorite else "Ajouter aux favoris"
        with action_col3:
            if st.button(
                fav_label,
                key=f"fav_{code_str}",
                help=fav_help,
                type="secondary",
                use_container_width=True,
            ):
                if is_favorite:
                    st.session_state.favorites = [
                        c for c in st.session_state.favorites if c != code_str
                    ]
                else:
                    st.session_state.favorites.append(code_str)
                st.rerun()
        st.markdown("---")

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
