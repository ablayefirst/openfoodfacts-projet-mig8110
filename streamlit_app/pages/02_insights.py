"""Tendances — schéma v3.

Changements :
- Valeurs nutritionnelles directement dans produit (plus de JOIN valeurs_nutritionnelles)
- categorie.nom_categorie (anciennement categorie.categorie)
- produit.id_produit (PK SERIAL), code_barre = identifiant externe
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection
from top_menu import render_top_menu

st.set_page_config(page_title="Tendances", layout="wide", initial_sidebar_state="collapsed")
render_top_menu("Tendances")

# ── Configuration des métriques ───────────────────────────────────
# Les expressions SQL pointent maintenant directement vers les colonnes de produit

METRIC_OPTIONS = {
    "Sucre (g/100g)": {
        "sql_expression": "p.sugars_100g",
        "kpi_label": "Sucre moyen", "axis_label": "Sucre moyen (g/100g)",
        "unit": "g/100g", "min_value": 0, "max_value": 50,
        "color": "#e76f51", "section_title": "Top 10 catégories les plus sucrées",
        "empty_message": "Aucune catégorie sucrée exploitable.", "sort_order": "DESC",
        "decimal_places": 2, "min_products": 5,
    },
    "Sel (g/100g)": {
        "sql_expression": "p.salt_100g",
        "kpi_label": "Sel moyen", "axis_label": "Sel moyen (g/100g)",
        "unit": "g/100g", "min_value": 0, "max_value": 10,
        "color": "#f4a261", "section_title": "Top 10 catégories les plus salées",
        "empty_message": "Aucune catégorie salée exploitable.", "sort_order": "DESC",
        "decimal_places": 2, "min_products": 5,
    },
    "Gras (g/100g)": {
        "sql_expression": "p.fat_100g",
        "kpi_label": "Gras moyen", "axis_label": "Gras moyen (g/100g)",
        "unit": "g/100g", "min_value": 0, "max_value": 100,
        "color": "#264653", "section_title": "Top 10 catégories les plus grasses",
        "empty_message": "Aucune catégorie grasse exploitable.", "sort_order": "DESC",
        "decimal_places": 2, "min_products": 5,
    },
    "Calories (kcal/100g)": {
        "sql_expression": "p.energy_kcal_100g",
        "kpi_label": "Calories moyennes", "axis_label": "Calories moyennes (kcal/100g)",
        "unit": "kcal/100g", "min_value": 0, "max_value": 900,
        "color": "#6d597a", "section_title": "Top 10 catégories les plus caloriques",
        "empty_message": "Aucune catégorie calorique exploitable.", "sort_order": "DESC",
        "decimal_places": 1, "min_products": 5,
    },
    "NutriScore moyen": {
        "sql_expression": "p.nutriscore_score",
        "kpi_label": "NutriScore moyen", "axis_label": "NutriScore moyen",
        "unit": "", "min_value": -15, "max_value": 40,
        "color": "#8ab17d", "section_title": "Top 10 catégories au meilleur NutriScore moyen",
        "empty_message": "Aucune catégorie avec NutriScore exploitable.", "sort_order": "ASC",
        "decimal_places": 1, "min_products": 5,
        "caption_suffix": "Pour le NutriScore, une valeur plus faible est meilleure.",
    },
}

st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)
st.title("Tendances des données – OpenFoodFacts")
st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)


def to_params_json(params=None) -> str:
    return json.dumps(params or {}, sort_keys=True)


@st.cache_data(ttl=300, show_spinner=False)
def run_query(sql: str, params_json: str = "{}"):
    params = json.loads(params_json)
    with get_connection() as conn:
        return pd.read_sql(sql, conn, params=params)


@st.cache_data(ttl=300, show_spinner=False)
def get_category_options():
    sql = """
    SELECT DISTINCT COALESCE(NULLIF(TRIM(categorie_principale), ''), 'autres') AS categorie
    FROM produit
    ORDER BY 1;
    """
    df = run_query(sql)
    return df["categorie"].tolist()


def render_vertical_bar_chart(dataframe, x_col, y_col, xlabel, ylabel, color):
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(dataframe[x_col], dataframe[y_col], color=color)
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    for bar in bars:
        value = bar.get_height()
        label = f"{value:.1f}" if value % 1 else f"{int(value)}"
        ax.text(bar.get_x() + bar.get_width() / 2, value, label, ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    return fig


def render_horizontal_bar_chart(dataframe, label_col, value_col, xlabel, color):
    plot_df = dataframe.iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.barh(plot_df[label_col], plot_df[value_col], color=color)
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    max_value = plot_df[value_col].max() if not plot_df.empty else 0
    offset = max(max_value * 0.02, 0.2)
    for bar in bars:
        value = bar.get_width()
        label = f"{value:.1f}" if value % 1 else f"{int(value)}"
        ax.text(value + offset, bar.get_y() + bar.get_height() / 2, label, va="center", fontsize=9)
    fig.tight_layout()
    return fig


def format_metric_value(value, metric_config):
    if pd.isna(value):
        return "N/A"
    decimals = metric_config["decimal_places"]
    return f"{float(value):.{decimals}f} {metric_config['unit']}".strip()


# ── Filtres ───────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)
with col1:
    nutriscore_filter = st.multiselect(
        "Filtrer NutriScore",
        options=["A", "B", "C", "D", "E", "N/A"],
        default=["A", "B", "C", "D", "E", "N/A"],
    )
with col2:
    category_filter = st.multiselect(
        "Filtrer catégorie principale",
        options=get_category_options(),
        placeholder="Toutes les catégories",
    )
with col3:
    metric_label = st.selectbox("Dimension nutritionnelle", options=list(METRIC_OPTIONS.keys()), index=0)

metric_config         = METRIC_OPTIONS[metric_label]
metric_sql_expression = metric_config["sql_expression"]

params = {}
filters_sql = ""

if nutriscore_filter:
    filters_sql += " AND UPPER(COALESCE(p.nutrition_grade, 'N/A')) = ANY(%(nutriscores)s)"
    params["nutriscores"] = nutriscore_filter

if category_filter:
    filters_sql += " AND COALESCE(NULLIF(TRIM(p.categorie_principale), ''), 'autres') = ANY(%(categories)s)"
    params["categories"] = category_filter

params_json = to_params_json(params)

# ── KPI ───────────────────────────────────────────────────────────

sql_kpis = f"""
WITH filtered_products AS (
    SELECT
        p.id_produit,
        UPPER(COALESCE(p.nutrition_grade, 'N/A')) AS nutriscore,
        COALESCE(NULLIF(TRIM(p.categorie_principale), ''), 'autres') AS categorie,
        {metric_sql_expression} AS metric_value
    FROM produit p
    WHERE 1=1
    {filters_sql}
),
top_category AS (
    SELECT categorie, COUNT(*) AS n_produits
    FROM filtered_products
    GROUP BY 1
    ORDER BY n_produits DESC, categorie
    LIMIT 1
)
SELECT
    COUNT(*)::int AS n_produits,
    ROUND(100.0 * AVG(CASE WHEN nutriscore <> 'N/A' THEN 1 ELSE 0 END), 1) AS pct_nutriscore,
    ROUND(
        AVG(CASE WHEN metric_value BETWEEN {metric_config["min_value"]} AND {metric_config["max_value"]}
                 THEN metric_value END),
        {metric_config["decimal_places"]}
    ) AS avg_metric_value,
    COALESCE((SELECT categorie FROM top_category), 'N/A') AS top_categorie
FROM filtered_products;
"""

df_kpis = run_query(sql_kpis, params_json)
kpis = df_kpis.iloc[0] if not df_kpis.empty else None

# ── Distribution NutriScore ───────────────────────────────────────

sql_nutriscore = f"""
SELECT
    UPPER(COALESCE(p.nutrition_grade, 'N/A')) AS nutriscore,
    COUNT(*)::int AS n
FROM produit p
WHERE 1=1 {filters_sql}
GROUP BY 1
ORDER BY nutriscore;
"""
df_nutri = run_query(sql_nutriscore, params_json)

# ── Top catégories volume ─────────────────────────────────────────

sql_top_categories = f"""
SELECT
    COALESCE(NULLIF(TRIM(p.categorie_principale), ''), 'autres') AS categorie,
    COUNT(DISTINCT p.id_produit)::int AS n_produits
FROM produit p
WHERE 1=1 {filters_sql}
GROUP BY 1
ORDER BY n_produits DESC
LIMIT 10;
"""
df_cat_count = run_query(sql_top_categories, params_json)

# ── Catégories par métrique ───────────────────────────────────────

sql_cat_metric = f"""
SELECT
    COALESCE(NULLIF(TRIM(p.categorie_principale), ''), 'autres') AS categorie,
    COUNT(*)::int AS n_produits,
    ROUND(AVG({metric_sql_expression}), {metric_config["decimal_places"]}) AS avg_metric_value
FROM produit p
WHERE {metric_sql_expression} IS NOT NULL
  AND {metric_sql_expression} BETWEEN {metric_config["min_value"]} AND {metric_config["max_value"]}
  {filters_sql}
GROUP BY 1
HAVING COUNT(*) >= {metric_config["min_products"]}
ORDER BY avg_metric_value {metric_config["sort_order"]}
LIMIT 10;
"""
df_cat_metric = run_query(sql_cat_metric, params_json)

# ── Affichage ─────────────────────────────────────────────────────

metric_cols = st.columns(4)
metric_cols[0].metric("Produits filtrés",
    int(kpis["n_produits"]) if kpis is not None and pd.notna(kpis["n_produits"]) else 0)
metric_cols[1].metric("Produits avec NutriScore",
    f"{float(kpis['pct_nutriscore']):.1f}%" if kpis is not None and pd.notna(kpis["pct_nutriscore"]) else "N/A")
metric_cols[2].metric(metric_config["kpi_label"],
    format_metric_value(kpis["avg_metric_value"], metric_config) if kpis is not None else "N/A")
metric_cols[3].metric("Catégorie dominante",
    kpis["top_categorie"] if kpis is not None and pd.notna(kpis["top_categorie"]) else "N/A")

st.markdown("<div style='margin-top: 0.5rem;'></div>", unsafe_allow_html=True)

colA, colB = st.columns(2)

with colA:
    st.subheader("Répartition NutriScore")
    if df_nutri.empty:
        st.info("Aucune donnée disponible pour les filtres sélectionnés.")
    else:
        st.pyplot(render_vertical_bar_chart(df_nutri, "nutriscore", "n", "NutriScore", "Nombre de produits", "#2a9d8f"))
        with st.expander("Voir les données NutriScore"):
            st.dataframe(df_nutri, use_container_width=True)

with colB:
    st.subheader("Top 10 catégories (volume)")
    if df_cat_count.empty:
        st.info("Aucune catégorie ne correspond aux filtres sélectionnés.")
    else:
        st.pyplot(render_horizontal_bar_chart(df_cat_count, "categorie", "n_produits", "Nombre de produits", "#457b9d"))
        with st.expander("Voir les données des catégories"):
            st.dataframe(df_cat_count, use_container_width=True)

st.subheader(metric_config["section_title"])
if df_cat_metric.empty:
    st.info(metric_config["empty_message"])
else:
    caption = (
        f"Le classement conserve uniquement les catégories avec au moins "
        f"{metric_config['min_products']} produits."
    )
    if "caption_suffix" in metric_config:
        caption = f"{caption} {metric_config['caption_suffix']}"
    st.caption(caption)
    st.pyplot(render_horizontal_bar_chart(
        df_cat_metric, "categorie", "avg_metric_value",
        metric_config["axis_label"], metric_config["color"],
    ))
    with st.expander("Voir les données détaillées"):
        st.dataframe(
            df_cat_metric.rename(columns={"avg_metric_value": metric_config["axis_label"]}),
            use_container_width=True,
        )
