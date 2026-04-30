"""Page principale Streamlit : tableau de bord Santé & Nutrition.

Nouveau schéma v3 :
- produit.id_produit (SERIAL PK), code_barre (TEXT UNIQUE)
- valeurs nutritionnelles directement dans produit (plus de table valeurs_nutritionnelles)
- marque.nom_marque (anciennement brands)
- categorie.nom_categorie (anciennement categorie)
- allergènes via produit_trace → trace → trace_allergene → allergene
"""

import math
import random
import sys
import warnings
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection
from top_menu import render_top_menu
from health_logic import HealthProfile, compute_personalized_scores
from image_utils import get_no_image_data_uri


# ── Helpers ──────────────────────────────────────────────────────

def clean_nutrient_value(value, max_reasonable: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if numeric > (max_reasonable * 10):
        numeric /= 100.0
    if numeric < 0 or numeric > max_reasonable:
        return float("nan")
    return numeric


def clean_nutrient_series(series: pd.Series, max_reasonable: float) -> pd.Series:
    return series.apply(lambda v: clean_nutrient_value(v, max_reasonable))


def format_grams(value: float) -> str:
    if pd.isna(value):
        return "Non applicable"
    return f"{value:.2f} g"


def shorten_text(text: str, max_length: int = 30) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


# ── Config page ───────────────────────────────────────────────────

st.set_page_config(page_title="Santé & Nutrition", layout="wide", initial_sidebar_state="collapsed")
render_top_menu("Dashboard")

# ── Session state ─────────────────────────────────────────────────

for key, default in [
    ("health_profile", None),
    ("use_health_profile", False),
    ("selected_code", None),
    ("home_selection", None),
    ("page", 1),
    ("compare_selection", []),
    ("favorites", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Connexion ─────────────────────────────────────────────────────

conn = get_connection()

# ── Catégories pour le filtre ─────────────────────────────────────

category_options = ["Toutes"]
try:
    df_categories = pd.read_sql(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(categorie_principale), ''), 'autres')
               AS categorie_principale
        FROM produit
        ORDER BY 1
        """,
        conn,
    )
    if not df_categories.empty:
        values = (
            df_categories["categorie_principale"]
            .dropna().astype(str).str.strip()
            .loc[lambda s: s != ""].unique().tolist()
        )
        category_options.extend(values)
except Exception:
    pass

# ── Filtres ───────────────────────────────────────────────────────

st.markdown("---")

st.markdown(
    """
    <style>
    div[class*="st-key-fav_"] button {
        min-width:3rem; padding:0.35rem 0.8rem; border-radius:999px;
        font-size:1.3rem; line-height:1;
        border:1px solid rgba(225,29,72,0.22); color:#e11d48;
        background:rgba(255,241,242,0.96); box-shadow:0 4px 10px rgba(225,29,72,0.08);
    }
    div[class*="st-key-fav_"] button[kind="primary"] {
        border-color:rgba(225,29,72,0.55); color:#ffffff;
        background:linear-gradient(135deg,#fb7185,#e11d48);
        box-shadow:0 8px 18px rgba(225,29,72,0.2);
    }
    div[class*="st-key-fav_"] button:hover {
        border-color:rgba(225,29,72,0.5); box-shadow:0 8px 18px rgba(225,29,72,0.16);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

col1, col2, col3 = st.columns(3)
with col1:
    search_name = st.text_input("Rechercher par nom")
with col2:
    selected_main_category = st.selectbox("Catégorie principale (exacte)", options=category_options, index=0)
with col3:
    max_sugar = st.number_input("Sucre max (g/100g)", min_value=0.0, value=50.0)

col4, col5, col6 = st.columns(3)
nutriscore_options = ["A", "B", "C", "D", "E"]
with col4:
    nutriscore_filter = st.multiselect("Filtrer NutriScore", options=nutriscore_options, default=nutriscore_options)
with col5:
    sort_option = st.selectbox("Trier par", ["NutriScore (A→E)", "Sucre (g/100g)", "Sel (g/100g)"])
with col6:
    sort_order = st.radio("Ordre", ("Croissant", "Décroissant"), horizontal=True)

category_detail_filter = st.text_input("Recherche libre dans catégories détaillées (optionnel)")

# ── Profil santé ──────────────────────────────────────────────────

health_profile = st.session_state.get("health_profile")
if health_profile is not None:
    label = (
        "Voir des alternatives plus saines pour moi"
        if not st.session_state.use_health_profile
        else "Désactiver les recommandations personnalisées"
    )
    if st.button(label):
        st.session_state.use_health_profile = not st.session_state.use_health_profile
    if st.session_state.use_health_profile:
        st.caption("Tri personnalisé activé en fonction de votre profil santé.")
else:
    st.caption("Définissez votre profil dans 'Mon profil santé' pour des recommandations personnalisées.")

# ── Reset pagination si filtres changent ──────────────────────────

profile_signature = None
hp = st.session_state.get("health_profile")
if isinstance(hp, HealthProfile):
    profile_signature = (float(getattr(hp, "sugar_penalty", 0.0)), float(getattr(hp, "salt_penalty", 0.0)))

current_filters_signature = (
    search_name, selected_main_category, float(max_sugar),
    tuple(nutriscore_filter), sort_option, sort_order,
    category_detail_filter, st.session_state.get("use_health_profile", False),
    profile_signature,
)

if "last_filters_signature" not in st.session_state:
    st.session_state["last_filters_signature"] = current_filters_signature
elif st.session_state["last_filters_signature"] != current_filters_signature:
    st.session_state.page = 1
    st.session_state.home_selection = None
    st.session_state["last_filters_signature"] = current_filters_signature

# ── Requête SQL principale ────────────────────────────────────────
# Nouveau schéma :
#   - valeurs nutritionnelles directement dans produit
#   - marque.nom_marque au lieu de marque.brands
#   - categorie.nom_categorie au lieu de categorie.categorie
#   - PK produit = id_produit, identifiant externe = code_barre

query = """
SELECT
    p.id_produit,
    p.code_barre                                                    AS code,
    p.nom_produit                                                   AS product_name,
    p.categorie_principale,
    p.nutrition_grade                                               AS nutriscore_grade,
    p.nova_group,
    p.image_url,
    p.sugars_100g,
    p.salt_100g,
    p.saturated_fat_100g,
    p.fiber_100g,
    p.proteins_100g,
    COALESCE(string_agg(DISTINCT c.nom_categorie, ', '), 'Non spécifiée') AS categories
FROM produit p
LEFT JOIN produit_categorie pc ON p.id_produit = pc.id_produit
LEFT JOIN categorie c ON pc.id_categorie = c.id_categorie
WHERE 1=1
"""

query_params = {"max_sugar": float(max_sugar)}

if search_name:
    query += " AND LOWER(p.nom_produit) LIKE LOWER(%(search_name)s)"
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
        WHERE pc2.id_produit = p.id_produit
          AND LOWER(c2.nom_categorie) LIKE LOWER(%(category_detail_filter)s)
    )
    """
    query_params["category_detail_filter"] = f"%{category_detail_filter}%"

query += " AND (p.sugars_100g IS NULL OR p.sugars_100g <= %(max_sugar)s)"

query += """
GROUP BY
    p.id_produit, p.code_barre, p.nom_produit, p.categorie_principale,
    p.nutrition_grade, p.nova_group, p.image_url,
    p.sugars_100g, p.salt_100g, p.saturated_fat_100g,
    p.fiber_100g, p.proteins_100g
"""

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning)

try:
    df = pd.read_sql(query, conn, params=query_params)
except Exception as e:
    st.error(f"Erreur lors du chargement des produits : {e}")
    df = pd.DataFrame(columns=[
        "id_produit", "code", "product_name", "categorie_principale",
        "nutriscore_grade", "nova_group", "image_url",
        "sugars_100g", "salt_100g", "saturated_fat_100g",
        "fiber_100g", "proteins_100g", "categories",
    ])

# Colonnes de sécurité
for col, default in [
    ("sugars_100g", pd.NA), ("salt_100g", pd.NA),
    ("nutriscore_grade", pd.NA), ("image_url", pd.NA),
    ("categories", "Non spécifiée"), ("code", ""),
]:
    if col not in df.columns:
        df[col] = default

# Colonnes nettoyées
df["sugars_clean"] = clean_nutrient_series(df["sugars_100g"], 50.0)
df["salt_clean"]   = clean_nutrient_series(df["salt_100g"],   25.0)

# Filtre NutriScore
nutri_series = df["nutriscore_grade"].fillna("").astype(str).str.upper()
if nutriscore_filter:
    df = df[nutri_series.isin(nutriscore_filter)]
    nutri_series = nutri_series.loc[df.index]
else:
    df = df.iloc[0:0]
    nutri_series = nutri_series.iloc[0:0]

# Tri
ascending = sort_order == "Croissant"
if sort_option == "NutriScore (A→E)":
    order_map = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    df = (df.assign(_nutri_rank=nutri_series.map(order_map).fillna(99))
            .sort_values("_nutri_rank", ascending=ascending)
            .drop(columns="_nutri_rank"))
elif sort_option == "Sucre (g/100g)":
    df = df.sort_values("sugars_clean", ascending=ascending, na_position="last")
elif sort_option == "Sel (g/100g)":
    df = df.sort_values("salt_clean",   ascending=ascending, na_position="last")

# Profil santé — tri personnalisé
use_health_profile = st.session_state.get("use_health_profile", False)
health_profile     = st.session_state.get("health_profile")

if use_health_profile and health_profile is not None and not df.empty:
    try:
        scores = compute_personalized_scores(df, health_profile)
        df = (df.assign(_personal_score=scores)
                .sort_values("_personal_score", ascending=False)
                .drop(columns="_personal_score"))
    except Exception as e:
        st.warning(f"Impossible d'appliquer le tri personnalisé : {e}")

if use_health_profile and health_profile is not None and not df.empty:
    try:
        sugar_penalty = float(getattr(health_profile, "sugar_penalty", 0.0))
        salt_penalty  = float(getattr(health_profile, "salt_penalty",  0.0))
        if sugar_penalty > 0.0:
            sugar_limit = 50.0 / (1.0 + sugar_penalty)
            df = df[(df["sugars_clean"].isna()) | (df["sugars_clean"] <= sugar_limit)]
        if salt_penalty > 0.0:
            salt_limit = 25.0 / (1.0 + salt_penalty)
            df = df[(df["salt_clean"].isna()) | (df["salt_clean"] <= salt_limit)]
    except Exception as e:
        st.warning(f"Impossible d'appliquer le filtre du profil santé : {e}")

# ── Pagination ────────────────────────────────────────────────────

is_home = (
    (not search_name)
    and (selected_main_category == "Toutes")
    and (not category_detail_filter)
    and max_sugar == 50.0
)

if is_home:
    if st.session_state.home_selection is None:
        if not df.empty:
            if use_health_profile and health_profile is not None:
                selection = df.head(10)
            else:
                mask_img = df["image_url"].notna() & df["image_url"].astype(str).str.strip().ne("")
                df_with_img = df[mask_img]
                if len(df_with_img) >= 10:
                    selection = df_with_img.sample(10, random_state=random.randint(0, 1_000_000))
                else:
                    needed = max(0, 10 - len(df_with_img))
                    df_without = df[~mask_img]
                    extras = (df_without.sample(min(needed, len(df_without)), random_state=random.randint(0, 1_000_000))
                              if needed > 0 and len(df_without) > 0 else pd.DataFrame())
                    selection = pd.concat([df_with_img, extras]).head(10)
            st.session_state.home_selection = selection.reset_index(drop=True)
        else:
            st.session_state.home_selection = df.copy()

    df_page = st.session_state.home_selection.copy()
    items_per_page = len(df_page)
    total_pages = 1
    st.session_state.page = 1
else:
    st.session_state.home_selection = None
    items_per_page = 10
    total_pages = max(1, math.ceil(len(df) / items_per_page))
    if st.session_state.page > total_pages:
        st.session_state.page = total_pages
    start  = (st.session_state.page - 1) * items_per_page
    df_page = df.iloc[start : start + items_per_page]

# ── Affichage cartes ──────────────────────────────────────────────

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
                st.info("Ouvrez la page 'Comparateur de produits' via le menu.")

cols = st.columns(2)

for index, row in df_page.iterrows():
    col = cols[index % 2]

    categories_display = row.get("categories", "Non spécifiée")
    if pd.notna(categories_display) and categories_display != "Non spécifiée":
        cats_list = [shorten_text(c.strip()) for c in str(categories_display).split(",") if c.strip()]
        categories_display = (", ".join(cats_list[:3]) + " ...") if len(cats_list) > 3 else ", ".join(cats_list)

    image_html = ""
    image_url  = row.get("image_url")
    if pd.notna(image_url) and str(image_url).strip():
        image_html = f'<img src="{image_url}" style="width:100%;height:100%;object-fit:cover;border-radius:8px;" />'
    else:
        no_img = get_no_image_data_uri()
        if no_img:
            image_html = f'<img src="{no_img}" style="width:100%;height:100%;object-fit:cover;border-radius:8px;" />'

    grade_upper = (row.get("nutriscore_grade") or "").upper()
    badge_html  = ""
    if grade_upper in ("A", "B"):
        badge_html = "<span style=\"background-color:#0f9d58;color:white;padding:2px 8px;border-radius:12px;font-size:12px;margin-left:6px;\">Top choix</span>"

    cat_princ = row.get("categorie_principale") or "autres"
    if pd.isna(cat_princ) or not str(cat_princ).strip():
        cat_princ = "autres"

    prod_name = row.get("product_name") or ""
    nutri_disp = row.get("nutriscore_grade") or "N/A"
    if pd.isna(nutri_disp) or not str(nutri_disp).strip():
        nutri_disp = "N/A"

    # On utilise code_barre comme identifiant externe (ou id_produit en fallback)
    code_str = str(row.get("code") or row.get("id_produit", ""))

    with col:
        st.markdown(
            f"""
            <div style="border:1px solid #ddd;padding:15px;border-radius:10px;margin-bottom:15px;
                        background-color:#fafafa;height:260px;display:flex;flex-direction:row;
                        gap:12px;box-sizing:border-box;">
                <div style="flex:0 0 40%;max-width:40%;display:flex;align-items:center;
                            justify-content:center;overflow:hidden;">{image_html}</div>
                <div style="flex:1 1 60%;max-width:60%;overflow:hidden;">
                    <h4 style="margin-top:0;margin-bottom:8px;word-wrap:break-word;
                               display:flex;align-items:center;gap:6px;">
                        <span>{prod_name}</span>{badge_html}
                    </h4>
                    <p style="margin:2px 0;"><b>Catégorie principale:</b> {cat_princ}</p>
                    <p style="margin:2px 0;"><b>Catégories détaillées:</b> {categories_display}</p>
                    <p style="margin:2px 0;"><b>NutriScore:</b> {nutri_disp}</p>
                    <p style="margin:2px 0;">Sucre: {format_grams(clean_nutrient_value(row['sugars_100g'], 50.0))}</p>
                    <p style="margin:2px 0;">Sel: {format_grams(clean_nutrient_value(row['salt_100g'], 25.0))}</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        a1, a2, a3 = st.columns([1.2, 1.1, 0.7])

        with a1:
            if st.button("Détails", key=f"detail_{code_str}", use_container_width=True):
                st.session_state.selected_code = code_str
                try:
                    st.query_params["code"] = code_str
                except AttributeError:
                    st.experimental_set_query_params(code=code_str)
                try:
                    st.switch_page("pages/01_detail_produit.py")
                except Exception:
                    st.info("Veuillez ouvrir la page 'Détail du produit' via le menu.")

        compare_selected = code_str in st.session_state.compare_selection
        with a2:
            new_value = st.checkbox("Comparer", value=compare_selected, key=f"compare_{code_str}")

        if new_value and not compare_selected:
            if len(st.session_state.compare_selection) >= 3:
                st.info("Maximum 3 produits. Décochez un produit avant d'en ajouter un autre.")
            else:
                st.session_state.compare_selection.append(code_str)
        elif not new_value and compare_selected:
            st.session_state.compare_selection = [c for c in st.session_state.compare_selection if c != code_str]

        is_favorite = code_str in st.session_state.favorites
        with a3:
            if st.button(
                "❤️" if is_favorite else "♡",
                key=f"fav_{code_str}",
                help="Retirer des favoris" if is_favorite else "Ajouter aux favoris",
                type="primary" if is_favorite else "secondary",
                use_container_width=True,
            ):
                if is_favorite:
                    st.session_state.favorites = [c for c in st.session_state.favorites if c != code_str]
                else:
                    st.session_state.favorites.append(code_str)

        st.markdown("---")

# ── Pagination ────────────────────────────────────────────────────

if not is_home:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("⬅️ Page précédente") and st.session_state.page > 1:
            st.session_state.page -= 1
            st.rerun()
    with c3:
        if st.button("Page suivante ➡️") and st.session_state.page < total_pages:
            st.session_state.page += 1
            st.rerun()
    st.write(f"Page {st.session_state.page} / {total_pages}")

try:
    conn.close()
except Exception:
    pass
