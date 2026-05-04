import sys
from pathlib import Path
from html import escape

import streamlit as st
import pandas as pd
import warnings

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection
from image_utils import get_no_image_data_uri
from top_menu import render_top_menu
from ui_hero import render_page_hero

st.set_page_config(page_title="Détail produit", layout="wide", initial_sidebar_state="collapsed")

render_top_menu("Dashboard")

render_page_hero(
    kicker="Analyse produit",
    title="Detail du produit",
    subtitle="Un resume clair du produit, avec les alternatives plus saines accessibles en un clic.",
)

conn = get_connection()

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

# ==============================
# PARAMÈTRES UTILISATEUR
# ==============================

SIMILARITY_MODE_OPTIONS = {
    "1 - Même catégorie": "meme_categorie",
    "2 - Profil nutritionnel": "profil_nutritionnel",
    "3 - Score nutritionnel global": "score_nutritionnel_global",
    "4 - Niveau de transformation (NOVA)": "niveau_transformation_nova",
   
}

HEALTHIER_MODE_OPTIONS = {
    "1 - Profil nutritionnel": "profil_nutritionnel",
    "2 - Score nutritionnel global": "score_nutritionnel_global",
    "3 - Niveau de transformation (NOVA)": "niveau_transformation_nova",
}

if "detail_similarity_mode_label" not in st.session_state:
    st.session_state["detail_similarity_mode_label"] = "1 - Même catégorie"

if "detail_healthier_mode_label" not in st.session_state:
    st.session_state["detail_healthier_mode_label"] = "1 - Profil nutritionnel"

with st.expander("Options avancees de recommandation", expanded=False):
    param_col1, param_col2 = st.columns(2)

    with param_col1:
        selected_similarity_label = st.selectbox(
            "Mode des produits similaires",
            options=list(SIMILARITY_MODE_OPTIONS.keys()),
            index=list(SIMILARITY_MODE_OPTIONS.keys()).index(
                st.session_state["detail_similarity_mode_label"]
            ),
            help="Choisissez comment les produits similaires sont recherchés."
        )

    with param_col2:
        selected_healthier_label = st.selectbox(
            "Mode des alternatives plus saines",
            options=list(HEALTHIER_MODE_OPTIONS.keys()),
            index=list(HEALTHIER_MODE_OPTIONS.keys()).index(
                st.session_state["detail_healthier_mode_label"]
            ),
            help="Choisissez comment les alternatives plus saines sont recherchées."
        )

    choice_col1, choice_col2 = st.columns(2)

    with choice_col1:
        show_similarity = st.checkbox("Produits similaires", value=False)

    with choice_col2:
        show_healthier = st.checkbox("Alternatives plus saines", value=True)

st.session_state["detail_similarity_mode_label"] = selected_similarity_label
st.session_state["detail_healthier_mode_label"] = selected_healthier_label

selected_similarity_method = SIMILARITY_MODE_OPTIONS[selected_similarity_label]
selected_healthier_method = HEALTHIER_MODE_OPTIONS[selected_healthier_label]

show_recommendations_warning = not show_similarity and not show_healthier

# ==============================
# RÉCUPÉRATION DU CODE PRODUIT
# ==============================

code = st.session_state.get("selected_code")

try:
    query_params = st.query_params
    query_code = query_params.get("code", None)
except AttributeError:
    query_params = st.experimental_get_query_params()
    query_code = query_params.get("code", None)

if isinstance(query_code, list):
    query_code = query_code[0] if query_code else None

if query_code is not None:
    query_code = str(query_code).strip()
    if query_code == "":
        query_code = None

# priorité au code de l'URL si présent
if query_code is not None:
    code = query_code
    st.session_state["selected_code"] = code

if code is None:
    st.warning("Aucun code produit trouvé dans la session ou dans l’URL.")
    missing_col1, missing_col2 = st.columns([0.72, 0.28])
    with missing_col1:
        missing_code = st.text_input(
            "Code produit / code-barres",
            placeholder="Ex. 737628064502",
        )
    with missing_col2:
        st.markdown("<div style='height:1.75rem;'></div>", unsafe_allow_html=True)
        if st.button("Ouvrir ce code", use_container_width=True):
            cleaned_code = missing_code.strip()
            if cleaned_code:
                st.session_state["selected_code"] = cleaned_code
                try:
                    st.query_params["code"] = cleaned_code
                except AttributeError:
                    st.experimental_set_query_params(code=cleaned_code)
                st.rerun()
    st.info("Vous pouvez aussi retourner au dashboard et cliquer sur le bouton 'Détails' d'un produit.")
    st.stop()

st.session_state.pop("detail_reco_error", None)

# synchronisation de l'URL
try:
    current_qp = st.query_params.get("code", None)
except AttributeError:
    current_qp = st.experimental_get_query_params().get("code", None)

if isinstance(current_qp, list):
    current_qp = current_qp[0] if current_qp else None

if str(current_qp) != str(code):
    try:
        st.query_params["code"] = str(code)
    except AttributeError:
        st.experimental_set_query_params(code=str(code))

PRODUCT_SEARCH_QUERY = """
SELECT
    p.code_produit AS code,
    p.nom_produit AS product_name,
    COALESCE(m.brands, 'Marque non specifiee') AS brand,
    COALESCE(p.categorie_principale, 'Categorie non specifiee') AS category,
    COALESCE(p.nutrition_grade, 'N/A') AS nutrition_grade,
    COALESCE(CAST(p.nova_group AS TEXT), 'N/A') AS nova_group
FROM produit p
LEFT JOIN marque m ON p.id_marque = m.id_marque
WHERE
    CAST(p.code_produit AS TEXT) ILIKE %s
    OR p.nom_produit ILIKE %s
    OR m.brands ILIKE %s
ORDER BY
    CASE
        WHEN CAST(p.code_produit AS TEXT) = %s THEN 0
        WHEN CAST(p.code_produit AS TEXT) ILIKE %s THEN 1
        WHEN p.nom_produit ILIKE %s THEN 2
        ELSE 3
    END,
    p.nom_produit ASC NULLS LAST
LIMIT 15
"""


def open_product(product_code) -> None:
    cleaned_code = str(product_code or "").strip()
    if not cleaned_code:
        return
    st.session_state["selected_code"] = cleaned_code
    try:
        st.query_params["code"] = cleaned_code
    except AttributeError:
        st.experimental_set_query_params(code=cleaned_code)
    st.rerun()


with st.expander("Changer de produit", expanded=False):
    product_lookup = st.text_input(
        "Rechercher par nom, marque ou code produit",
        value=st.session_state.get("detail_product_lookup", ""),
        placeholder="Ex. olive, nutella, 737628, 0009300187084",
    )
    st.session_state["detail_product_lookup"] = product_lookup

    lookup_clean = product_lookup.strip()
    if lookup_clean:
        lookup_like = f"%{lookup_clean}%"
        lookup_prefix = f"{lookup_clean}%"
        search_df = pd.read_sql(
            PRODUCT_SEARCH_QUERY,
            conn,
            params=(
                lookup_like,
                lookup_like,
                lookup_like,
                lookup_clean,
                lookup_prefix,
                lookup_prefix,
            ),
        )

        if search_df.empty:
            st.warning("Aucun produit trouve pour cette recherche.")
        else:
            selected_idx = st.selectbox(
                "Produits trouves",
                options=list(range(len(search_df))),
                format_func=lambda idx: (
                    f"{search_df.iloc[idx]['product_name'] or 'Produit sans nom'} "
                    f"- {search_df.iloc[idx]['brand']} "
                    f"({search_df.iloc[idx]['code']})"
                ),
            )
            selected_product = search_df.iloc[selected_idx]
            st.caption(
                f"Categorie: {selected_product['category']} | "
                f"NutriScore: {str(selected_product['nutrition_grade']).upper()} | "
                f"NOVA: {selected_product['nova_group']}"
            )
            if st.button("Ouvrir le produit selectionne", use_container_width=True):
                open_product(selected_product["code"])

# ==============================
# REQUÊTES SQL
# ==============================

DETAIL_QUERY = r"""
SELECT
    p.code_produit AS code,
    p.nom_produit AS product_name,
    p.categorie_principale,
    p.quantite,
    p.nutrition_grade,
    p.nutriscore_score,
    p.nova_group,
    p.url,
    p.image_url,
    p.image_small_url,
    p.image_nutrition_url,
    m.brands AS brand,
    COALESCE(string_agg(DISTINCT c.categorie, ', '), 'Non spécifiée') AS categories,
    COALESCE(
        string_agg(DISTINCT ing.ingredients_nom, ', ' ORDER BY ing.ingredients_nom)
        FILTER (
            WHERE ing.ingredients_nom IS NOT NULL
              AND TRIM(ing.ingredients_nom) <> ''
              AND TRIM(ing.ingredients_nom) !~* '^(and|or)\s+|\s+(and|or)$'
        ),
        'Non spécifiés'
    ) AS ingredients,
    COALESCE(string_agg(DISTINCT a.allergens, ', '), 'Non spécifiés') AS allergens,
    COALESCE(string_agg(DISTINCT lb.labels, ', '), 'Non spécifiés') AS labels,
    COALESCE(string_agg(DISTINCT pays.countries_en, ', '), 'Non spécifiés') AS countries,
    v.saturated_fat_100g,
    v.sugars_100g,
    v.fiber_100g,
    v.proteins_100g,
    v.salt_100g,
    v.carbohydrates_100g,
    v.fat_100g
FROM produit p
LEFT JOIN marque m ON p.id_marque = m.id_marque
LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
LEFT JOIN produit_categorie pc ON p.code_produit = pc.code_produit
LEFT JOIN categorie c ON pc.id_categorie = c.id_categorie
LEFT JOIN produit_ingredient pi ON p.code_produit = pi.code_produit
LEFT JOIN ingredient ing ON pi.id_ingredient = ing.id_ingredient
LEFT JOIN produit_allergene pa ON p.code_produit = pa.code_produit
LEFT JOIN allergene a ON pa.allergen_id = a.allergen_id
LEFT JOIN produit_label pl ON p.code_produit = pl.code_produit
LEFT JOIN label lb ON pl.label_id = lb.label_id
LEFT JOIN produit_pays pp ON p.code_produit = pp.code_produit
LEFT JOIN pays ON pp.id_pays = pays.id_pays
WHERE p.code_produit = %s
GROUP BY
    p.code_produit, p.nom_produit, p.categorie_principale, p.quantite,
    p.nutrition_grade, p.nutriscore_score, p.nova_group,
    p.url, p.image_url, p.image_small_url,
    p.image_nutrition_url,
    m.brands,
    v.saturated_fat_100g, v.sugars_100g, v.fiber_100g,
    v.proteins_100g, v.salt_100g, v.carbohydrates_100g,
    v.fat_100g
"""

SIMILAR_PRODUCTS_QUERY = """
SELECT
    ps.code_produit_cible,
    ps.score_similarite,
    ps.nb_ingredients_communs,
    ps.ingredients_communs,
    ps.methode,
    ps.mode_sante,
    ps.type_recommandation,
    ps.health_score_source,
    ps.health_score_cible,
    p.nom_produit,
    p.image_url,
    p.image_small_url,
    p.nutrition_grade,
    p.nova_group,
    p.categorie_principale,
    v.sugars_100g,
    v.salt_100g,
    v.saturated_fat_100g,
    v.fiber_100g,
    v.proteins_100g
FROM produit_similaire ps
JOIN produit p
    ON ps.code_produit_cible = p.code_produit
LEFT JOIN valeurs_nutritionnelles v
    ON p.code_produit = v.code_produit
WHERE ps.code_produit_source = %s
  AND ps.type_recommandation = 'similaire'
  AND ps.methode = %s
ORDER BY ps.score_similarite DESC
LIMIT 5
"""

HEALTHIER_PRODUCTS_QUERY = """
SELECT
    ps.code_produit_cible,
    ps.score_similarite,
    ps.nb_ingredients_communs,
    ps.ingredients_communs,
    ps.methode,
    ps.mode_sante,
    ps.type_recommandation,
    ps.health_score_source,
    ps.health_score_cible,
    p.nom_produit,
    p.image_url,
    p.image_small_url,
    p.nutrition_grade,
    p.nova_group,
    p.categorie_principale,
    v.sugars_100g,
    v.salt_100g,
    v.saturated_fat_100g,
    v.fiber_100g,
    v.proteins_100g
FROM produit_similaire ps
JOIN produit p
    ON ps.code_produit_cible = p.code_produit
LEFT JOIN valeurs_nutritionnelles v
    ON p.code_produit = v.code_produit
WHERE ps.code_produit_source = %s
  AND ps.type_recommandation = 'plus_saine'
  AND ps.methode = %s
ORDER BY ps.score_similarite DESC
LIMIT 5
"""

RECOMMENDATION_COLUMNS = [
    "code_produit_cible",
    "score_similarite",
    "nb_ingredients_communs",
    "ingredients_communs",
    "nom_produit",
    "image_url",
    "image_small_url",
    "nutrition_grade",
    "nova_group",
    "categorie_principale",
    "sugars_100g",
    "salt_100g",
    "saturated_fat_100g",
    "fiber_100g",
    "proteins_100g",
]


def read_optional_recommendations(query: str, product_code: str, method: str) -> pd.DataFrame:
    """Load optional recommendation data without breaking the detail page.

    The recommendations table is populated by a separate process and may not
    exist yet in some environments. In that case we keep the page usable and
    simply return an empty result.
    """

    try:
        return pd.read_sql(query, conn, params=(product_code, method))
    except Exception as exc:
        st.session_state["detail_reco_error"] = str(exc)
        return pd.DataFrame(columns=RECOMMENDATION_COLUMNS)

detail_df = pd.read_sql(DETAIL_QUERY, conn, params=(code,))

if detail_df.empty:
    st.error("Produit introuvable.")
    st.stop()

row = detail_df.iloc[0]



# ✅ état affichage
if "show_nutri" not in st.session_state:
    st.session_state.show_nutri = False

# 🔘 bouton toggle
if st.button("📊 Analyser le profil nutritionnel"):
    st.session_state.show_nutri = not st.session_state.show_nutri

# 👇 affichage conditionnel
if st.session_state.show_nutri:

    sugar = row.get("sugars_100g") or 0
    salt = row.get("salt_100g") or 0
    fat_sat = row.get("saturated_fat_100g") or 0
    fiber = row.get("fiber_100g") or 0
    proteins = row.get("proteins_100g") or 0

    values = {
        "Sucre": float(sugar),
        "Sel": float(salt),
        "Graisses saturées": float(fat_sat),
        "Fibres": float(fiber),
        "Protéines": float(proteins)
    }

    st.markdown("### 📊 Profil nutritionnel")
    import matplotlib.pyplot as plt

    colors = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6"]
  
    fig, ax = plt.subplots(figsize=(4, 2))

    labels = ["Sucre", "Sel", "Graisses saturées", "Fibres", "Protéines"]

    ax.bar(labels, values.values(), color=colors)

    # 🔽 corrige le chevauchement
    ax.set_xticklabels(labels, rotation=30, ha='right')

    # 🔽 taille texte
    ax.tick_params(axis='x', labelsize=8)
    ax.tick_params(axis='y', labelsize=8)

    ax.set_ylabel("g / 100g", fontsize=9)

    # 🔽 style clean
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # 🔥 IMPORTANT
    plt.tight_layout()

    st.pyplot(fig, use_container_width=False)
    


similar_df = read_optional_recommendations(SIMILAR_PRODUCTS_QUERY, code, selected_similarity_method)
healthier_df = read_optional_recommendations(HEALTHIER_PRODUCTS_QUERY, code, selected_healthier_method)

# ==============================
# FICHE PRODUIT (AFFICHEE AVANT ANALYSE)
# ==============================

st.markdown(
    """
    <style>
    .product-sheet {
        border: 1px solid rgba(15,118,110,0.22);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        background:
            radial-gradient(300px 110px at 5% 0%, rgba(20,184,166,0.09), transparent 90%),
            radial-gradient(320px 130px at 95% 100%, rgba(245,158,11,0.09), transparent 90%),
            #ffffff;
        box-shadow: 0 6px 18px rgba(15,23,42,0.06);
        margin-bottom: 1rem;
        display: flex;
        flex-direction: column;
    }
    .product-sheet .product-image-frame {
        flex: 1;
    }
    .product-title {
        margin: 0;
        font-size: 1.35rem;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.2;
    }
    .product-code {
        margin-top: 0.3rem;
        color: #64748b;
        font-size: 0.9rem;
    }
    .info-chip {
        display: inline-block;
        margin: 0.2rem 0.35rem 0.2rem 0;
        padding: 0.25rem 0.55rem;
        border-radius: 999px;
        border: 1px solid rgba(15,118,110,0.24);
        background: rgba(20,184,166,0.08);
        color: #0f172a;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .nutri-badge {
        display: inline-block;
        padding: 4px 11px;
        border-radius: 999px;
        font-size: 0.84rem;
        font-weight: 800;
        letter-spacing: 0.04em;
        margin-right: 0.35rem;
    }
    .nutri-a { background:#1a7f37; color:#fff; }
    .nutri-b { background:#85c341; color:#fff; }
    .nutri-c { background:#f7c948; color:#1a1a1a; }
    .nutri-d { background:#ef8c14; color:#fff; }
    .nutri-e { background:#e63e11; color:#fff; }
    .nutri-na { background:#cbd5e1; color:#475569; }
    .nova-badge {
        display: inline-block;
        padding: 4px 11px;
        border-radius: 999px;
        font-size: 0.82rem;
        font-weight: 700;
        color: #fff;
        background: #0f766e;
    }
    .section-label {
        margin: 0.35rem 0 0.15rem;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: #0f766e;
    }
    .nutrition-box {
        border: 1px solid rgba(148,163,184,0.3);
        border-radius: 12px;
        background: #f8fafc;
        padding: 0.55rem 0.7rem;
        margin-bottom: 0.45rem;
    }
    .nutrition-line {
        margin: 0.18rem 0;
        color: #0f172a;
        font-size: 0.9rem;
    }
    .product-image-frame {
        border: 1px solid rgba(148,163,184,0.3);
        border-radius: 14px;
        background: #f8fafc;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        height: 100%;
        max-height: 460px;
        min-height: 360px;
    }
    .product-image-frame img {
        width: 100%;
        height: auto;
        object-fit: contain;
    }
    .analysis-card {
        border: 1px solid rgba(15,118,110,0.22);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        background:
            radial-gradient(280px 100px at 5% 0%, rgba(20,184,166,0.08), transparent 90%),
            radial-gradient(300px 120px at 95% 100%, rgba(245,158,11,0.08), transparent 90%),
            #ffffff;
        box-shadow: 0 6px 18px rgba(15,23,42,0.06);
        margin-bottom: 0.9rem;
    }
    .analysis-title {
        margin: 0;
        font-size: 1.08rem;
        font-weight: 800;
        color: #0f172a;
    }
    .analysis-sub {
        margin: 0.25rem 0 0.8rem;
        color: #64748b;
        font-size: 0.88rem;
    }
    .score-big {
        margin: 0.3rem 0;
        font-size: 2rem;
        line-height: 1;
        font-weight: 800;
        color: #0f766e;
    }
    .status-chip {
        display: inline-block;
        padding: 0.25rem 0.55rem;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 700;
        margin-bottom: 0.4rem;
    }
    .status-good { color: #14532d; background: #dcfce7; }
    .status-mid { color: #92400e; background: #fef3c7; }
    .status-bad { color: #7f1d1d; background: #fee2e2; }
    .alert-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    .alert-item {
        border-radius: 10px;
        padding: 0.45rem 0.6rem;
        margin-bottom: 0.42rem;
        font-size: 0.9rem;
        border: 1px solid transparent;
    }
    .alert-item.error {
        background: #fef2f2;
        border-color: #fecaca;
        color: #991b1b;
    }
    .alert-item.warning {
        background: #fffbeb;
        border-color: #fde68a;
        color: #92400e;
    }
    .alert-item.success {
        background: #f0fdf4;
        border-color: #bbf7d0;
        color: #166534;
    }
    .exp-list {
        margin: 0;
        padding-left: 1rem;
        color: #0f172a;
        font-size: 0.92rem;
    }
    .exp-list li { margin: 0.22rem 0; }
    .score-breakdown {
        list-style: none;
        margin: 0.65rem 0 0;
        padding: 0;
    }
    .score-breakdown li {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.7rem;
        border-top: 1px solid rgba(148,163,184,0.22);
        padding: 0.38rem 0;
        color: #334155;
        font-size: 0.88rem;
    }
    .delta-positive { color: #15803d; font-weight: 800; }
    .delta-negative { color: #b91c1c; font-weight: 800; }
    .delta-neutral { color: #64748b; font-weight: 800; }
    .badge-wrap {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem;
        margin: 0.35rem 0 0.55rem;
    }
    .detail-badge {
        display: inline-flex;
        align-items: center;
        padding: 0.25rem 0.55rem;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 800;
        border: 1px solid transparent;
    }
    .badge-ingredient { background: #f8fafc; color: #334155; border-color: #cbd5e1; }
    .badge-allergen { background: #fee2e2; color: #991b1b; border-color: #fecaca; }
    .badge-label { background: #dcfce7; color: #166534; border-color: #bbf7d0; }
    .replace-card {
        border: 1px solid rgba(15,118,110,0.22);
        border-radius: 14px;
        padding: 0.9rem 1rem;
        margin-bottom: 0.8rem;
        background: #ffffff;
        box-shadow: 0 5px 14px rgba(15,23,42,0.05);
    }
    .replace-title {
        margin: 0 0 0.25rem;
        color: #0f172a;
        font-size: 1.05rem;
        font-weight: 800;
    }
    .reason-list {
        margin: 0.45rem 0;
        padding-left: 1rem;
        color: #334155;
        font-size: 0.9rem;
    }
    .reason-list li { margin: 0.16rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


def split_display_values(value: str, limit: int = 8) -> list[str]:
    if pd.isna(value) or str(value).strip() in ("", "Non spécifiés", "Non spécifiée"):
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()][:limit]


def render_detail_badges(values: list[str], badge_class: str) -> str:
    if not values:
        return "<span style='color:#64748b;font-size:0.88rem;'>Non spécifiés</span>"
    return (
        "<div class='badge-wrap'>"
        + "".join(
            f"<span class='detail-badge {badge_class}'>{escape(value[:42])}</span>"
            for value in values
        )
        + "</div>"
    )


def safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def grade_rank(grade) -> int | None:
    return {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}.get(str(grade).strip().upper())


def build_replacement_reasons(source_row, candidate_row) -> list[str]:
    reasons = []

    comparisons = [
        ("sugars_100g", "moins de sucre", "g/100g", False),
        ("salt_100g", "moins de sel", "g/100g", False),
        ("saturated_fat_100g", "moins de graisses saturées", "g/100g", False),
        ("fiber_100g", "plus de fibres", "g/100g", True),
        ("proteins_100g", "plus de protéines", "g/100g", True),
    ]
    for key, label, unit, higher_is_better in comparisons:
        source_value = safe_float(source_row.get(key))
        candidate_value = safe_float(candidate_row.get(key))
        if source_value is None or candidate_value is None:
            continue
        improvement = candidate_value - source_value if higher_is_better else source_value - candidate_value
        if improvement > 0:
            reasons.append(
                f"{label}: {source_value:.1f} -> {candidate_value:.1f} {unit}"
            )

    source_grade = grade_rank(source_row.get("nutrition_grade"))
    candidate_grade = grade_rank(candidate_row.get("nutrition_grade"))
    if source_grade is not None and candidate_grade is not None and candidate_grade > source_grade:
        reasons.append(
            f"meilleur NutriScore: {str(source_row.get('nutrition_grade')).upper()} -> {str(candidate_row.get('nutrition_grade')).upper()}"
        )

    source_nova = safe_float(source_row.get("nova_group"))
    candidate_nova = safe_float(candidate_row.get("nova_group"))
    if source_nova is not None and candidate_nova is not None and candidate_nova < source_nova:
        reasons.append(f"NOVA plus faible: {int(source_nova)} -> {int(candidate_nova)}")

    if not reasons:
        reasons.append("profil global plus favorable selon le score santé calculé")
    return reasons[:5]


product_name = row.get("product_name", "Produit sans nom")
product_code = row.get("code", "N/A")
brand = row.get("brand", "Non spécifiée")
quantite = row.get("quantite", "Non spécifiée")
category_main = row.get("categorie_principale", "autres")
categories = row.get("categories", "Non spécifiée")
countries = row.get("countries", "Non spécifiés")
ingredient_values = split_display_values(row.get("ingredients"), limit=40)
allergen_values = split_display_values(row.get("allergens"), limit=8)
label_values = split_display_values(row.get("labels"), limit=8)
nutrition_grade_display = str(row.get("nutrition_grade", "N/A") or "N/A").upper()
nutri_score_display = row.get("nutriscore_score", "N/A")
nova_display = row.get("nova_group", "N/A")

main_img = row.get("image_url") or row.get("image_small_url") or row.get("image_nutrition_url")

nutri_css_map = {
    "A": "nutri-a",
    "B": "nutri-b",
    "C": "nutri-c",
    "D": "nutri-d",
    "E": "nutri-e",
}
nutri_class = nutri_css_map.get(nutrition_grade_display, "nutri-na")

left_col, right_col = st.columns([0.34, 0.66])

with left_col:
    st.markdown("<div class='product-sheet'>", unsafe_allow_html=True)
    image_src = ""
    if pd.notna(main_img) and str(main_img).strip() != "":
        image_src = str(main_img)
    else:
        no_image_data = get_no_image_data_uri()
        if no_image_data:
            image_src = no_image_data

    if image_src:
        st.markdown(
            f"<div class='product-image-frame'><img src='{image_src}' alt='Image produit' /></div>",
            unsafe_allow_html=True,
        )

    if pd.notna(row.get("url")) and str(row.get("url")).strip() != "":
        st.markdown(f"[Fiche OpenFoodFacts]({row['url']})")
    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown("<div class='product-sheet'>", unsafe_allow_html=True)
    st.markdown(f"<h3 class='product-title'>{product_name}</h3>", unsafe_allow_html=True)
    st.markdown(f"<p class='product-code'>Code produit : {product_code}</p>", unsafe_allow_html=True)

    st.markdown(
        f"<span class='nutri-badge {nutri_class}'>NutriScore {nutrition_grade_display}</span>"
        f"<span class='nova-badge'>NOVA {nova_display}</span>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<div style='margin-top:0.45rem;'>"
        f"<span class='info-chip'>Marque: {brand}</span>"
        f"<span class='info-chip'>Quantite: {quantite}</span>"
        f"<span class='info-chip'>Categorie principale: {category_main}</span>"
        f"<span class='info-chip'>NutriScore numerique: {nutri_score_display}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<p class='section-label'>Profil rapide pour 100g</p>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class='nutrition-box'>
            <p class='nutrition-line'><b>Sucre :</b> {row.get('sugars_100g', 'N/A')} g</p>
            <p class='nutrition-line'><b>Sel :</b> {row.get('salt_100g', 'N/A')} g</p>
            <p class='nutrition-line'><b>Graisses saturées :</b> {row.get('saturated_fat_100g', 'N/A')} g</p>
            <p class='nutrition-line'><b>Fibres :</b> {row.get('fiber_100g', 'N/A')} g</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

# ==============================
# VARIABLES NUTRITIONNELLES
# ==============================

sugar = row.get("sugars_100g")
salt = row.get("salt_100g")
fat_sat = row.get("saturated_fat_100g")
fiber = row.get("fiber_100g")
proteins = row.get("proteins_100g")
nova = row.get("nova_group")
nutriscore = str(row.get("nutrition_grade", "")).upper()

# ==============================
# FONCTION SCORE SANTÉ OMS
# ==============================

def compute_health_score_oms(sugar, salt, fat_sat, fiber, proteins, nova, nutriscore):
    """
    Score santé inspiré des recommandations OMS.

    Le score est calculé sur 100 :
    - forte pénalité pour sucre, sel, graisses saturées
    - bonus pour fibres
    - petit bonus pour protéines
    - ajustement complémentaire avec NOVA et NutriScore

    Plus le score est élevé, plus le produit est intéressant sur le plan nutritionnel.
    """

    score = 100.0

    WHO_SUGAR_IDEAL = 25.0
    WHO_SUGAR_MAX = 50.0
    WHO_SALT_MAX = 5.0
    WHO_SAT_FAT_MAX = 22.0
    WHO_FIBER_MIN = 25.0

    try:
        if sugar is not None and pd.notna(sugar):
            sugar = float(sugar)
            sugar_ratio_ideal = sugar / WHO_SUGAR_IDEAL
            sugar_ratio_max = sugar / WHO_SUGAR_MAX

            if sugar <= 5:
                score -= 0
            elif sugar <= 10:
                score -= 5
            elif sugar <= 20:
                score -= 12
            elif sugar <= 25:
                score -= 18
            else:
                score -= 25

            score -= min(sugar_ratio_ideal * 2, 6)
            score -= min(sugar_ratio_max, 2)
    except (TypeError, ValueError):
        pass

    try:
        if salt is not None and pd.notna(salt):
            salt = float(salt)
            salt_ratio = salt / WHO_SALT_MAX

            if salt <= 0.3:
                score -= 0
            elif salt <= 0.6:
                score -= 4
            elif salt <= 1.2:
                score -= 10
            elif salt <= 1.5:
                score -= 15
            else:
                score -= 22

            score -= min(salt_ratio * 3, 6)
    except (TypeError, ValueError):
        pass

    try:
        if fat_sat is not None and pd.notna(fat_sat):
            fat_sat = float(fat_sat)
            sat_ratio = fat_sat / WHO_SAT_FAT_MAX

            if fat_sat <= 1.5:
                score -= 0
            elif fat_sat <= 3:
                score -= 4
            elif fat_sat <= 5:
                score -= 9
            elif fat_sat <= 10:
                score -= 16
            else:
                score -= 24

            score -= min(sat_ratio * 3, 6)
    except (TypeError, ValueError):
        pass

    try:
        if fiber is not None and pd.notna(fiber):
            fiber = float(fiber)
            fiber_ratio = fiber / WHO_FIBER_MIN

            if fiber >= 6:
                score += 10
            elif fiber >= 3:
                score += 5
            elif fiber > 0:
                score += 2

            score += min(fiber_ratio * 2, 5)
    except (TypeError, ValueError):
        pass

    try:
        if proteins is not None and pd.notna(proteins):
            proteins = float(proteins)

            if proteins >= 10:
                score += 4
            elif proteins >= 5:
                score += 2
    except (TypeError, ValueError):
        pass

    try:
        if nova is not None and pd.notna(nova):
            nova = int(nova)

            if nova == 4:
                score -= 8
            elif nova == 3:
                score -= 3
            elif nova == 2:
                score -= 1
    except (TypeError, ValueError):
        pass

    try:
        nutriscore = str(nutriscore).upper()

        if nutriscore == "A":
            score += 8
        elif nutriscore == "B":
            score += 5
        elif nutriscore == "C":
            score += 0
        elif nutriscore == "D":
            score -= 6
        elif nutriscore == "E":
            score -= 12
    except Exception:
        pass

    score = max(0, min(100, score))
    return round(score, 2)


def compute_health_score_breakdown(sugar, salt, fat_sat, fiber, proteins, nova, nutriscore):
    """Retourne les bonus et pénalités qui expliquent le score santé."""

    breakdown = []

    try:
        if sugar is not None and pd.notna(sugar):
            sugar_val = float(sugar)
            penalty = 0.0
            if sugar_val <= 5:
                penalty = 0.0
            elif sugar_val <= 10:
                penalty = 5.0
            elif sugar_val <= 20:
                penalty = 12.0
            elif sugar_val <= 25:
                penalty = 18.0
            else:
                penalty = 25.0
            penalty += min((sugar_val / 25.0) * 2, 6)
            penalty += min(sugar_val / 50.0, 2)
            breakdown.append(("Sucre", -penalty, f"{sugar_val:.1f} g/100g"))
    except (TypeError, ValueError):
        pass

    try:
        if salt is not None and pd.notna(salt):
            salt_val = float(salt)
            penalty = 0.0
            if salt_val <= 0.3:
                penalty = 0.0
            elif salt_val <= 0.6:
                penalty = 4.0
            elif salt_val <= 1.2:
                penalty = 10.0
            elif salt_val <= 1.5:
                penalty = 15.0
            else:
                penalty = 22.0
            penalty += min((salt_val / 5.0) * 3, 6)
            breakdown.append(("Sel", -penalty, f"{salt_val:.1f} g/100g"))
    except (TypeError, ValueError):
        pass

    try:
        if fat_sat is not None and pd.notna(fat_sat):
            fat_sat_val = float(fat_sat)
            penalty = 0.0
            if fat_sat_val <= 1.5:
                penalty = 0.0
            elif fat_sat_val <= 3:
                penalty = 4.0
            elif fat_sat_val <= 5:
                penalty = 9.0
            elif fat_sat_val <= 10:
                penalty = 16.0
            else:
                penalty = 24.0
            penalty += min((fat_sat_val / 22.0) * 3, 6)
            breakdown.append(("Graisses saturées", -penalty, f"{fat_sat_val:.1f} g/100g"))
    except (TypeError, ValueError):
        pass

    try:
        if fiber is not None and pd.notna(fiber):
            fiber_val = float(fiber)
            bonus = 0.0
            if fiber_val >= 6:
                bonus += 10.0
            elif fiber_val >= 3:
                bonus += 5.0
            elif fiber_val > 0:
                bonus += 2.0
            bonus += min((fiber_val / 25.0) * 2, 5)
            breakdown.append(("Fibres", bonus, f"{fiber_val:.1f} g/100g"))
    except (TypeError, ValueError):
        pass

    try:
        if proteins is not None and pd.notna(proteins):
            proteins_val = float(proteins)
            bonus = 4.0 if proteins_val >= 10 else 2.0 if proteins_val >= 5 else 0.0
            breakdown.append(("Protéines", bonus, f"{proteins_val:.1f} g/100g"))
    except (TypeError, ValueError):
        pass

    try:
        if nova is not None and pd.notna(nova):
            nova_val = int(nova)
            penalty = 8.0 if nova_val == 4 else 3.0 if nova_val == 3 else 1.0 if nova_val == 2 else 0.0
            breakdown.append(("NOVA", -penalty, f"groupe {nova_val}"))
    except (TypeError, ValueError):
        pass

    nutriscore_val = str(nutriscore).upper()
    nutri_delta = {"A": 8.0, "B": 5.0, "C": 0.0, "D": -6.0, "E": -12.0}.get(nutriscore_val, 0.0)
    breakdown.append(("NutriScore", nutri_delta, nutriscore_val or "N/A"))

    return breakdown


def format_score_delta(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f} pts"


def mode_explanation(label):
    if label == "1 - Même catégorie":
        return "Produits proches selon l’appartenance à la même catégorie principale."
    elif label == "2 - Profil nutritionnel":
        return "Produits proches selon la proximité du sucre, du sel, des graisses saturées, des fibres et des protéines."
    elif label == "3 - Score nutritionnel global":
        return "Produits proches selon la proximité du score nutritionnel global basé sur le NutriScore."
    elif label == "4 - Niveau de transformation (NOVA)":
        return "Produits proches selon la proximité du niveau de transformation alimentaire."
    elif label == "1 - Profil nutritionnel":
        return "Alternatives plus saines selon la proximité du sucre, du sel, des graisses saturées, des fibres et des protéines."
    elif label == "2 - Score nutritionnel global":
        return "Alternatives plus saines selon le score nutritionnel global basé sur le NutriScore."
    elif label == "3 - Niveau de transformation (NOVA)":
        return "Alternatives plus saines selon le niveau de transformation alimentaire."
    return ""


def show_similarity_extra_info(sim_row, selected_method):
    if selected_method == "meme_categorie":
        st.markdown("**Logique :** même catégorie principale.")
    elif selected_method == "profil_nutritionnel":
        st.markdown("**Logique :** proximité du profil nutritionnel.")
    elif selected_method == "score_nutritionnel_global":
        st.markdown("**Logique :** proximité du NutriScore.")
    elif selected_method == "niveau_transformation_nova":
        st.markdown("**Logique :** proximité du groupe NOVA.")


def render_recommendation_section(
    title,
    selected_label,
    selected_method,
    df_results,
    button_prefix,
    show_health_scores=False,
):
    st.markdown(f"## {title}")
    st.caption(f"Mode sélectionné : {selected_label}")
    st.caption(mode_explanation(selected_label))

    if df_results.empty:
        st.info(f"Aucun résultat trouvé pour : {selected_label}.")
        return

    for _, sim in df_results.iterrows():
        if show_health_scores:
            reasons = build_replacement_reasons(row, sim)
            reason_html = "".join(f"<li>{escape(reason)}</li>" for reason in reasons)
            score_source = sim.get("health_score_source", "N/A")
            score_target = sim.get("health_score_cible", "N/A")
            st.markdown("<div class='replace-card'>", unsafe_allow_html=True)
            col1, col2 = st.columns([0.22, 0.78])

            with col1:
                sim_img = sim.get("image_url") or sim.get("image_small_url")
                if pd.notna(sim_img) and str(sim_img).strip() != "":
                    st.image(str(sim_img), width=130)
                else:
                    no_image_data = get_no_image_data_uri()
                    if no_image_data:
                        st.image(no_image_data, width=130)

            with col2:
                st.markdown(
                    f"<p class='replace-title'>Remplacer par {escape(str(sim.get('nom_produit', 'Produit sans nom')))}</p>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"**Score santé :** {score_source} -> {score_target} &nbsp; "
                    f"**NutriScore :** {sim.get('nutrition_grade', 'N/A')} &nbsp; "
                    f"**NOVA :** {sim.get('nova_group', 'N/A')}"
                )
                st.markdown(f"<ul class='reason-list'>{reason_html}</ul>", unsafe_allow_html=True)
                st.caption(f"Similarité : {sim.get('score_similarite', 0)} · Catégorie : {sim.get('categorie_principale', 'Non spécifiée')}")

                button_key = f"{button_prefix}_{selected_method}_{sim['code_produit_cible']}"
                if st.button(f"Voir détail {sim['code_produit_cible']}", key=button_key):
                    st.session_state["selected_code"] = sim["code_produit_cible"]
                    try:
                        st.query_params["code"] = str(sim["code_produit_cible"])
                    except AttributeError:
                        st.experimental_set_query_params(code=str(sim["code_produit_cible"]))
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)
            continue

        col1, col2 = st.columns([0.25, 0.75])

        with col1:
            sim_img = sim.get("image_url") or sim.get("image_small_url")
            if pd.notna(sim_img) and str(sim_img).strip() != "":
                st.image(str(sim_img), width=120)
            else:
                no_image_data = get_no_image_data_uri()
                if no_image_data:
                    st.image(no_image_data, width=120)

        with col2:
            st.markdown(f"### {sim.get('nom_produit', 'Produit sans nom')}")
            st.markdown(f"**Score de similarité :** {sim.get('score_similarite', 0)}")
            st.markdown(f"**Catégorie :** {sim.get('categorie_principale', 'Non spécifiée')}")
            st.markdown(f"**NutriScore :** {sim.get('nutrition_grade', 'N/A')}")
            st.markdown(f"**Groupe NOVA :** {sim.get('nova_group', 'N/A')}")

            if show_health_scores:
                st.markdown(f"**Score santé source :** {sim.get('health_score_source', 'N/A')}")
                st.markdown(f"**Score santé cible :** {sim.get('health_score_cible', 'N/A')}")

            show_similarity_extra_info(sim, selected_method)

            button_key = f"{button_prefix}_{selected_method}_{sim['code_produit_cible']}"
            button_label = f"Voir détail {sim['code_produit_cible']}"

            if st.button(button_label, key=button_key):
                st.session_state["selected_code"] = sim["code_produit_cible"]
                try:
                    st.query_params["code"] = str(sim["code_produit_cible"])
                except AttributeError:
                    st.experimental_set_query_params(code=str(sim["code_produit_cible"]))
                st.rerun()

        st.markdown("---")


# ==============================
# 🚨 SYSTÈME D’ALERTES
# ==============================

alerts = []
has_major_alert = False

try:
    if pd.notna(sugar) and float(sugar) > 15:
        alerts.append(("error", f" Produit très sucré ({float(sugar):.1f} g/100g)"))
        has_major_alert = True
    elif pd.notna(sugar) and float(sugar) > 10:
        alerts.append(("warning", f" Produit assez sucré ({float(sugar):.1f} g/100g)"))
except (TypeError, ValueError) as e:
    st.error(f"Erreur lors de la vérification du sucre : {e}")

try:
    if pd.notna(salt) and float(salt) > 1.5:
        alerts.append(("error", f" Produit très salé ({float(salt):.1f} g/100g)"))
        has_major_alert = True
    elif pd.notna(salt) and float(salt) > 0.6:
        alerts.append(("warning", f" Produit assez salé ({float(salt):.1f} g/100g)"))
except (TypeError, ValueError) as e:
    st.error(f"Erreur lors de la vérification du sel : {e}")

try:
    if pd.notna(fat_sat) and float(fat_sat) > 5:
        alerts.append(("warning", f" Riche en graisses saturées ({float(fat_sat):.1f} g/100g)"))
        has_major_alert = True
    elif pd.notna(fat_sat) and float(fat_sat) > 3:
        alerts.append(("warning", f" Graisses saturées modérées ({float(fat_sat):.1f} g/100g)"))
except (TypeError, ValueError):
    pass

try:
    if pd.notna(nova) and int(nova) == 4:
        alerts.append(("error", " Produit ultra-transformé (NOVA 4)"))
        has_major_alert = True
    elif pd.notna(nova) and int(nova) == 3:
        alerts.append(("warning", " Produit transformé (NOVA 3)"))
except (TypeError, ValueError):
    pass

if nutriscore in ["D", "E"]:
    alerts.append(("error", f" Qualité nutritionnelle faible (NutriScore {nutriscore})"))
    has_major_alert = True
elif nutriscore == "C":
    alerts.append(("warning", " Qualité nutritionnelle moyenne (NutriScore C)"))

if nutriscore in ["A", "B"] and not has_major_alert:
    alerts.append(("success", " Bon choix nutritionnel"))

# ==============================
# SCORE SANTÉ ET LECTURE SIMPLIFIÉE
# ==============================

score = compute_health_score_oms(
    sugar=sugar,
    salt=salt,
    fat_sat=fat_sat,
    fiber=fiber,
    proteins=proteins,
    nova=nova,
    nutriscore=nutriscore
)
score_breakdown = compute_health_score_breakdown(
    sugar=sugar,
    salt=salt,
    fat_sat=fat_sat,
    fiber=fiber,
    proteins=proteins,
    nova=nova,
    nutriscore=nutriscore,
)

explications = []

try:
    if pd.notna(sugar):
        sugar_val = float(sugar)
        if sugar_val > 15:
            explications.append(f"Teneur en sucre très élevée ({sugar_val:.1f} g/100g).")
        elif sugar_val > 10:
            explications.append(f"Teneur en sucre assez élevée ({sugar_val:.1f} g/100g).")
except (TypeError, ValueError):
    pass

try:
    if pd.notna(salt):
        salt_val = float(salt)
        if salt_val > 1.5:
            explications.append(f"Teneur en sel élevée ({salt_val:.1f} g/100g).")
        elif salt_val > 0.6:
            explications.append(f"Teneur en sel modérée ({salt_val:.1f} g/100g).")
except (TypeError, ValueError):
    pass

try:
    if pd.notna(fat_sat):
        fat_sat_val = float(fat_sat)
        if fat_sat_val > 5:
            explications.append(f"Graisses saturées élevées ({fat_sat_val:.1f} g/100g).")
        elif fat_sat_val > 3:
            explications.append(f"Graisses saturées modérées ({fat_sat_val:.1f} g/100g).")
except (TypeError, ValueError):
    pass

try:
    if pd.notna(nova):
        nova_val = int(nova)
        if nova_val == 4:
            explications.append("Produit ultra-transformé (NOVA 4).")
        elif nova_val == 3:
            explications.append("Produit transformé (NOVA 3).")
except (TypeError, ValueError):
    pass

if nutriscore in ["D", "E"]:
    explications.append(f"NutriScore {nutriscore} : qualité nutritionnelle faible.")
elif nutriscore == "C":
    explications.append("NutriScore C : qualité nutritionnelle moyenne.")
elif nutriscore in ["A", "B"]:
    explications.append("Bonne qualité nutritionnelle globale.")

try:
    if pd.notna(fiber) and float(fiber) >= 3:
        explications.append("Apport intéressant en fibres.")
except (TypeError, ValueError):
    pass

try:
    if pd.notna(proteins) and float(proteins) >= 5:
        explications.append("Bonne source de protéines.")
except (TypeError, ValueError):
    pass

if score >= 75:
    niveau_risque = "bon"
elif score >= 50:
    niveau_risque = "modéré"
else:
    niveau_risque = "élevé"

if niveau_risque == "élevé":
    status_class = "status-bad"
    status_text = "Risque eleve"
    score_hint = "Produit a consommer avec moderation."
elif niveau_risque == "modéré":
    status_class = "status-mid"
    status_text = "Risque modere"
    score_hint = "Produit acceptable avec quelques limites nutritionnelles."
else:
    status_class = "status-good"
    status_text = "Bon profil"
    score_hint = "Produit globalement interessant sur le plan nutritionnel."

alerts_html = ""
for level, message in alerts:
    alerts_html += f"<li class='alert-item {level}'>{escape(message)}</li>"

if not alerts_html:
    alerts_html = "<li class='alert-item success'>Aucune alerte nutritionnelle majeure detectee.</li>"

breakdown_html = ""
for label, delta, context in score_breakdown:
    delta_class = "delta-positive" if delta > 0 else "delta-negative" if delta < 0 else "delta-neutral"
    breakdown_html += (
        f"<li>"
        f"<span><b>{escape(label)}</b><br><small>{escape(context)}</small></span>"
        f"<span class='{delta_class}'>{format_score_delta(delta)}</span>"
        f"</li>"
    )

if not breakdown_html:
    breakdown_html = "<li><span>Aucun facteur chiffré disponible.</span><span class='delta-neutral'>0.0 pts</span></li>"

exp_html = ""
if explications:
    for exp in explications:
        exp_html += f"<li>{escape(exp)}</li>"
else:
    exp_html = "<li>Aucune explication additionnelle.</li>"

summary_tab, alternatives_tab, details_tab = st.tabs(
    ["Resume", "Alternatives", "Details"]
)

with summary_tab:
    st.markdown("## Resume nutritionnel", unsafe_allow_html=True)
    analysis_col1, analysis_col2, analysis_col3 = st.columns([0.33, 0.33, 0.34])

    with analysis_col1:
        st.markdown(
            f"""
            <div class='analysis-card'>
                <p class='analysis-title'>Score sante</p>
                <p class='analysis-sub'>Evaluation globale inspiree des recommandations OMS</p>
                <p class='score-big'>{round(score, 2)} <span style='font-size:1rem; font-weight:700; color:#64748b;'>/ 100</span></p>
                <span class='status-chip {status_class}'>{status_text}</span>
                <p style='margin:0.35rem 0 0; color:#334155; font-size:0.9rem;'>{score_hint}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with analysis_col2:
        st.markdown(
            f"""
            <div class='analysis-card'>
                <p class='analysis-title'>Alertes cles</p>
                <p class='analysis-sub'>Points sensibles detectes automatiquement</p>
                <ul class='alert-list'>
                    {alerts_html}
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with analysis_col3:
        st.markdown(
            f"""
            <div class='analysis-card'>
                <p class='analysis-title'>A retenir</p>
                <p class='analysis-sub'>Lecture courte du produit</p>
                <ul class='exp-list'>
                    {exp_html}
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("Voir le calcul du score sante", expanded=False):
        st.markdown(f"<ul class='score-breakdown'>{breakdown_html}</ul>", unsafe_allow_html=True)

with alternatives_tab:
    if show_recommendations_warning:
        st.warning("Veuillez sélectionner au moins un type de recommandation pour afficher les suggestions.")

    if st.session_state.get("detail_reco_error"):
        st.info("Les recommandations ne sont pas encore disponibles dans cette base de données.")

    if show_healthier:
        render_recommendation_section(
            title="Remplacer par...",
            selected_label=selected_healthier_label,
            selected_method=selected_healthier_method,
            df_results=healthier_df,
            button_prefix="healthy",
            show_health_scores=True,
        )

    if show_similarity:
        with st.expander("Produits similaires", expanded=False):
            render_recommendation_section(
                title="Produits similaires",
                selected_label=selected_similarity_label,
                selected_method=selected_similarity_method,
                df_results=similar_df,
                button_prefix="sim",
                show_health_scores=False,
            )

with details_tab:
    st.markdown("### Informations produit")
    product_info_rows = [
        {"Champ": "Code produit", "Valeur": product_code},
        {"Champ": "Nom", "Valeur": product_name},
        {"Champ": "Marque", "Valeur": brand},
        {"Champ": "Quantite", "Valeur": quantite},
        {"Champ": "Categorie principale", "Valeur": category_main},
        {"Champ": "Categories", "Valeur": categories},
        {"Champ": "Pays", "Valeur": countries},
    ]
    st.dataframe(product_info_rows, use_container_width=True, hide_index=True)

    st.markdown("### Valeurs nutritionnelles pour 100g")
    nutrition_rows = [
        {"Nutriment": "Glucides", "Valeur": row.get("carbohydrates_100g", "N/A"), "Unite": "g"},
        {"Nutriment": "Graisses", "Valeur": row.get("fat_100g", "N/A"), "Unite": "g"},
        {"Nutriment": "Graisses saturees", "Valeur": row.get("saturated_fat_100g", "N/A"), "Unite": "g"},
        {"Nutriment": "Sucre", "Valeur": row.get("sugars_100g", "N/A"), "Unite": "g"},
        {"Nutriment": "Fibres", "Valeur": row.get("fiber_100g", "N/A"), "Unite": "g"},
        {"Nutriment": "Proteines", "Valeur": row.get("proteins_100g", "N/A"), "Unite": "g"},
        {"Nutriment": "Sel", "Valeur": row.get("salt_100g", "N/A"), "Unite": "g"},
    ]
    st.dataframe(nutrition_rows, use_container_width=True, hide_index=True)

    st.markdown("### Ingrédients déclarés")
    st.markdown(render_detail_badges(ingredient_values, "badge-ingredient"), unsafe_allow_html=True)

    detail_col1, detail_col2 = st.columns(2)
    with detail_col1:
        st.markdown("### Allergenes")
        st.markdown(render_detail_badges(allergen_values, "badge-allergen"), unsafe_allow_html=True)
    with detail_col2:
        st.markdown("### Labels")
        st.markdown(render_detail_badges(label_values, "badge-label"), unsafe_allow_html=True)

    if pd.notna(row.get("url")) and str(row.get("url")).strip() != "":
        st.markdown(f"[Fiche OpenFoodFacts]({row['url']})")

try:
    conn.close()
except Exception:
    pass




