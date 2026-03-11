import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from db_connection import get_connection

st.set_page_config(page_title="Insights", layout="wide")
st.title("📊 Insights – OpenFoodFacts Canada")

# ---------- DB helper ----------
def run_query(sql: str, params=None):
    with get_connection() as conn:
        return pd.read_sql(sql, conn, params=params)

# =====================================
# 🔎 FILTRES
# =====================================

col1, col2 = st.columns(2)

with col1:
    nutriscore_filter = st.multiselect(
        "Filtrer NutriScore",
        options=["A", "B", "C", "D", "E"],
        default=["A", "B", "C", "D", "E"],
    )

with col2:
    category_filter = st.text_input("Filtrer catégorie principale (texte)")

params = {}
filters_sql = ""

if nutriscore_filter:
    filters_sql += " AND UPPER(p.nutrition_grade) = ANY(%(nutriscores)s)"
    params["nutriscores"] = nutriscore_filter

if category_filter:
    filters_sql += " AND LOWER(COALESCE(p.categorie_principale, '')) LIKE LOWER(%(cat_filter)s)"
    params["cat_filter"] = f"%{category_filter}%"

# =====================================
# 1️⃣ Distribution NutriScore
# =====================================

sql_nutriscore = f"""
SELECT
  UPPER(COALESCE(p.nutrition_grade, 'N/A')) AS nutriscore,
  COUNT(*)::int AS n
FROM produit p
WHERE 1=1
{filters_sql}
GROUP BY 1
ORDER BY nutriscore;
"""

df_nutri = run_query(sql_nutriscore, params)

# =====================================
# 2️⃣ Top catégories (volume)
# =====================================

sql_top_categories = f"""
SELECT
  COALESCE(NULLIF(TRIM(p.categorie_principale), ''), 'autres') AS categorie,
  COUNT(DISTINCT p.code_produit)::int AS n_produits
FROM produit p
WHERE 1=1
{filters_sql}
GROUP BY 1
ORDER BY n_produits DESC
LIMIT 10;
"""

df_cat_count = run_query(sql_top_categories, params)

# =====================================
# 3️⃣ Catégories les plus sucrées
# =====================================

sql_cat_sugar = f"""
SELECT
  COALESCE(NULLIF(TRIM(p.categorie_principale), ''), 'autres') AS categorie,
  AVG(v.sugars_100g) AS avg_sugars_100g
FROM produit p
JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
WHERE v.sugars_100g IS NOT NULL
  AND v.sugars_100g BETWEEN 0 AND 50
  {filters_sql}
GROUP BY 1
HAVING COUNT(*) >= 5
ORDER BY avg_sugars_100g DESC
LIMIT 10;
"""

df_cat_sugar = run_query(sql_cat_sugar, params)

# =====================================
# 📊 AFFICHAGE
# =====================================

colA, colB = st.columns(2)

with colA:
    st.subheader("Répartition NutriScore")
    st.dataframe(df_nutri, use_container_width=True)

    fig = plt.figure()
    plt.bar(df_nutri["nutriscore"], df_nutri["n"])
    plt.xlabel("NutriScore")
    plt.ylabel("Nombre de produits")
    st.pyplot(fig)

with colB:
    st.subheader("Top 10 catégories (volume)")
    st.dataframe(df_cat_count, use_container_width=True)

    fig = plt.figure()
    plt.barh(df_cat_count["categorie"][::-1], df_cat_count["n_produits"][::-1])
    plt.xlabel("Nombre de produits")
    st.pyplot(fig)

st.subheader("Top 10 catégories les plus sucrées")
st.dataframe(
    df_cat_sugar.assign(
        avg_sugars_100g=df_cat_sugar["avg_sugars_100g"].round(2)
    ),
    use_container_width=True,
)

fig = plt.figure()
plt.barh(df_cat_sugar["categorie"][::-1], df_cat_sugar["avg_sugars_100g"][::-1])
plt.xlabel("Sucre moyen (g/100g)")
st.pyplot(fig)
