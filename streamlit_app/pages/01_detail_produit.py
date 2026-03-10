import streamlit as st
import pandas as pd
import warnings

from db_connection import get_connection

st.set_page_config(page_title="Détail produit", layout="wide")

st.title("Détail du produit")

conn = get_connection()

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

# Récupérer le code produit sélectionné depuis la page principale ou l'URL
code = st.session_state.get("selected_code")

try:
    query_params = st.query_params
except AttributeError:
    query_params = st.experimental_get_query_params()

query_code = query_params.get("code")
if isinstance(query_code, list):
    query_code = query_code[0] if query_code else None

if code is None and query_code is not None:
    code = str(query_code).strip()
    if code:
        st.session_state.selected_code = code
    else:
        code = None

if code is None:
    fallback_sql = """
    SELECT code_produit
    FROM produit
    WHERE image_url IS NOT NULL AND TRIM(image_url) <> ''
    LIMIT 1
    """
    fallback_df = pd.read_sql(fallback_sql, conn)

    if fallback_df.empty:
        fallback_df = pd.read_sql("SELECT code_produit FROM produit LIMIT 1", conn)

    if fallback_df.empty:
        st.error("Aucun produit disponible dans la base.")
        st.stop()

    code = str(fallback_df.iloc[0]["code_produit"]).strip()
    st.session_state.selected_code = code
    st.info("Aucun produit sélectionné. Affichage du premier produit disponible.")

query_code_str = str(query_code) if query_code is not None else None

if query_code_str != str(code):
    try:
        st.query_params["code"] = str(code)
    except AttributeError:
        st.experimental_set_query_params(code=str(code))

# Requête SQL pour tous les détails du produit
DETAIL_QUERY = """
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
    p.image_ingredients_url,
    p.image_ingredients_small_url,
    p.image_nutrition_url,
    m.brands AS brand,
    COALESCE(string_agg(DISTINCT c.categorie, ', '), 'Non spécifiée') AS categories,
    COALESCE(string_agg(DISTINCT ing.ingredients_nom, ', '), 'Non spécifiés') AS ingredients,
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
    p.image_ingredients_url, p.image_ingredients_small_url,
    p.image_nutrition_url,
    m.brands,
    v.saturated_fat_100g, v.sugars_100g, v.fiber_100g,
    v.proteins_100g, v.salt_100g, v.carbohydrates_100g,
    v.fat_100g
"""


detail_df = pd.read_sql(DETAIL_QUERY, conn, params=(code,))

if detail_df.empty:
    st.error("Produit introuvable.")
    st.stop()

row = detail_df.iloc[0]

# En-tête avec bouton retour
col_title = st.columns([0.8, 0.2])[0]

with col_title:
    st.subheader(f"{row['product_name']}")
    st.caption(f"Code produit : {row['code']}")

# Bloc principal image + infos
col_img, col_info = st.columns([0.6, 0.6])

with col_img:
    main_img = row.get("image_url") or row.get("image_small_url") or row.get("image_nutrition_url")
    if pd.notna(main_img) and str(main_img).strip() != "":
        st.image(str(main_img), width=420)
    if pd.notna(row.get("url")) and str(row.get("url")).strip() != "":
        st.markdown(f"[Fiche OpenFoodFacts]({row['url']})")

with col_info:
    categorie_principale_display = row.get("categorie_principale", "autres")
    if pd.isna(categorie_principale_display) or str(categorie_principale_display).strip() == "":
        categorie_principale_display = "autres"

    st.markdown(f"**Marque :** {row.get('brand', 'Non spécifiée')}")
    st.markdown(f"**Quantité :** {row.get('quantite', 'Non spécifiée')}")
    st.markdown(f"**Catégorie principale :** {categorie_principale_display}")
    st.markdown(f"**Catégories :** {row.get('categories', 'Non spécifiée')}")
    st.markdown(f"**Pays :** {row.get('countries', 'Non spécifiés')}")
    st.markdown(f"**NutriScore :** {row.get('nutrition_grade', 'N/A')} (score {row.get('nutriscore_score', 'N/A')})")
    st.markdown(f"**Groupe NOVA :** {row.get('nova_group', 'N/A')}")

    st.markdown("---")
    st.markdown("**Détails nutritionnels (pour 100g)**")
    st.markdown(f"- Glucides : {row.get('carbohydrates_100g', 'N/A')} g")
    st.markdown(f"- Graisses : {row.get('fat_100g', 'N/A')} g (dont saturées {row.get('saturated_fat_100g', 'N/A')} g)")
    st.markdown(f"- Sucre : {row.get('sugars_100g', 'N/A')} g")
    st.markdown(f"- Fibres : {row.get('fiber_100g', 'N/A')} g")
    st.markdown(f"- Protéines : {row.get('proteins_100g', 'N/A')} g")
    st.markdown(f"- Sel : {row.get('salt_100g', 'N/A')} g")

st.markdown("---")

st.markdown("**Ingrédients**")
st.write(row.get("ingredients", "Non spécifiés"))

st.markdown("**Allergènes**")
st.write(row.get("allergens", "Non spécifiés"))

st.markdown("**Labels**")
st.write(row.get("labels", "Non spécifiés"))
