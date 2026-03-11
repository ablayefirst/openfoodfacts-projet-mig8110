import streamlit as st
import pandas as pd
import warnings
from db_connection import get_connection

# -------------------------------------------------
# CONFIGURATION PAGE
# -------------------------------------------------

st.set_page_config(page_title="Détail produit", layout="wide")

st.markdown("""
<style>

.stApp{
    background-color:#f8f5ef;
}

.card{
    border:1px solid #222;
    border-radius:16px;
    padding:16px;
    background:white;
    margin-bottom:10px;
    box-shadow:0 4px 10px rgba(0,0,0,0.08);
}

.nutrition-box{
    background:#f2f2f2;
    padding:12px;
    border-radius:12px;
    font-size:15px;
}

.product-title{
    text-align:center;
    font-weight:600;
    margin-top:10px;
    margin-bottom:10px;
}

</style>
""", unsafe_allow_html=True)

st.title("Détail du produit")

conn = get_connection()
warnings.filterwarnings("ignore", category=UserWarning)

# -------------------------------------------------
# RECUPERATION PRODUIT
# -------------------------------------------------

code = st.session_state.get("selected_code")

try:
    query_params = st.query_params
except:
    query_params = st.experimental_get_query_params()

query_code = query_params.get("code")

if isinstance(query_code, list):
    query_code = query_code[0] if query_code else None

if code is None and query_code:
    code = str(query_code)
    st.session_state.selected_code = code

if code is None:
    fallback = pd.read_sql("SELECT code_produit FROM produit LIMIT 1", conn)

    if fallback.empty:
        st.error("Aucun produit disponible.")
        st.stop()

    code = str(fallback.iloc[0]["code_produit"])

# -------------------------------------------------
# REQUETE DETAIL PRODUIT
# -------------------------------------------------

DETAIL_QUERY = """
SELECT
p.code_produit AS code,
p.nom_produit AS product_name,
p.nutrition_grade,
p.nova_group,
p.image_url,
p.image_ingredients_url,
p.image_nutrition_url,
m.brands AS brand,
COALESCE(string_agg(DISTINCT c.categorie, ', '),'Non spécifiée') AS categories,
COALESCE(string_agg(DISTINCT ing.ingredients_nom, ', '),'Non spécifiés') AS ingredients,
COALESCE(string_agg(DISTINCT a.allergens, ', '),'Non spécifiés') AS allergens,
v.sugars_100g,
v.salt_100g,
v.fat_100g,
v.saturated_fat_100g,
v.proteins_100g,
v.fiber_100g
FROM produit p
LEFT JOIN marque m ON p.id_marque = m.id_marque
LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
LEFT JOIN produit_categorie pc ON p.code_produit = pc.code_produit
LEFT JOIN categorie c ON pc.id_categorie = c.id_categorie
LEFT JOIN produit_ingredient pi ON p.code_produit = pi.code_produit
LEFT JOIN ingredient ing ON pi.id_ingredient = ing.id_ingredient
LEFT JOIN produit_allergene pa ON p.code_produit = pa.code_produit
LEFT JOIN allergene a ON pa.allergen_id = a.allergen_id
WHERE p.code_produit = %s
GROUP BY
p.code_produit,p.nom_produit,
p.nutrition_grade,p.nova_group,
p.image_url,p.image_ingredients_url,p.image_nutrition_url,
m.brands,
v.sugars_100g,v.salt_100g,v.fat_100g,
v.saturated_fat_100g,v.proteins_100g,v.fiber_100g
"""

detail_df = pd.read_sql(DETAIL_QUERY, conn, params=(code,))

if detail_df.empty:
    st.error("Produit introuvable.")
    st.stop()

row = detail_df.iloc[0]

# -------------------------------------------------
# HEADER PRODUIT
# -------------------------------------------------

col_img, col_info = st.columns([1,1])

with col_img:

    tabs = st.tabs(["Produit","Ingrédients","Nutrition"])

    if pd.notna(row["image_url"]):
        tabs[0].image(row["image_url"], use_container_width=True)

    if pd.notna(row["image_ingredients_url"]):
        tabs[1].image(row["image_ingredients_url"], use_container_width=True)

    if pd.notna(row["image_nutrition_url"]):
        tabs[2].image(row["image_nutrition_url"], use_container_width=True)

with col_info:

    st.subheader(row["product_name"])

    grade = str(row.get("nutrition_grade","")).upper()

    color_map={
        "A":"#0f9d58",
        "B":"#66bb6a",
        "C":"#fbc02d",
        "D":"#f57c00",
        "E":"#d32f2f"
    }

    badge_color=color_map.get(grade,"#9e9e9e")

    st.markdown(f"""
    <div style="
    padding:8px 18px;
    background:{badge_color};
    color:white;
    font-weight:bold;
    border-radius:20px;
    display:inline-block;">
    NutriScore {grade}
    </div>
    """,unsafe_allow_html=True)

    st.markdown(f"**Marque :** {row.get('brand','N/A')}")
    st.markdown(f"**Catégories :** {row.get('categories','N/A')}")
    st.markdown(f"**NOVA :** {row.get('nova_group','N/A')}")

# -------------------------------------------------
# METRICS NUTRITION
# -------------------------------------------------

st.markdown("## Informations nutritionnelles (100g)")

c1,c2,c3 = st.columns(3)

c1.metric("🍬 Sucre", f"{row['sugars_100g']:.2f} g")
c2.metric("🧂 Sel", f"{row['salt_100g']:.2f} g")
c3.metric("🧈 Graisses", f"{row['fat_100g']:.2f} g")

c4,c5,c6 = st.columns(3)

c4.metric("🔥 Saturées", f"{row['saturated_fat_100g']:.2f} g")
c5.metric("💪 Protéines", f"{row['proteins_100g']:.2f} g")
c6.metric("🌾 Fibres", f"{row['fiber_100g']:.2f} g")

# -------------------------------------------------
# INGREDIENTS
# -------------------------------------------------

st.markdown("## Ingrédients")
st.write(row["ingredients"])

st.markdown("## Allergènes")
st.write(row["allergens"])

# -------------------------------------------------
# SUGGESTIONS
# -------------------------------------------------

st.markdown("---")
st.markdown("## 🥗 Suggestions des produits similaires")

current_categories=row["categories"]

if current_categories and current_categories!="Non spécifiée":

    first_category=current_categories.split(",")[0].strip()

    SUGGESTION_QUERY="""
    SELECT
    p.code_produit,
    p.nom_produit,
    p.image_url,
    v.sugars_100g,
    v.salt_100g,
    v.fat_100g,
    v.saturated_fat_100g,
    v.proteins_100g,
    v.fiber_100g
    FROM produit p
    JOIN valeurs_nutritionnelles v
    ON p.code_produit=v.code_produit
    JOIN produit_categorie pc
    ON p.code_produit=pc.code_produit
    JOIN categorie c
    ON pc.id_categorie=c.id_categorie
    WHERE c.categorie ILIKE %s
    AND p.code_produit<>%s

    """

    suggestion_df=pd.read_sql(
        SUGGESTION_QUERY,
        conn,
        params=(f"%{first_category}%",code)
    )

    if not suggestion_df.empty:

        def compare(value,current):

            try:
                value=float(value)
                current=float(current)
            except:
                return "<span style='color:gray;'>N/A</span>"

            value_str=f"{value:.2f}"

            if value<current:
                return f"<span style='color:green;'>↓ {value_str} g</span>"
            elif value>current:
                return f"<span style='color:red;'>↑ {value_str} g</span>"
            else:
                return f"<span style='color:gray;'>= {value_str} g</span>"

        for i in range(0,len(suggestion_df),2):

            cols=st.columns(2, gap="large")

            for j in range(2):

                if i+j>=len(suggestion_df):
                    continue

                sug=suggestion_df.iloc[i+j]

                with cols[j]:

                    st.markdown(f"""
<div class="card">

<img src="{sug['image_url']}" 
style="
width:90%;
height:220px;
object-fit:cover;
border-radius:12px;
display:block;
margin-left:auto;
margin-right:auto;
">

<h4 class="product-title">
{sug['nom_produit']}
</h4>

<div class="nutrition-box">

<div style="
display:grid;
grid-template-columns:1fr 1fr;
gap:8px;
">

<div>🍬 Sucre {compare(sug['sugars_100g'],row['sugars_100g'])}</div>
<div>🧂 Sel {compare(sug['salt_100g'],row['salt_100g'])}</div>
<div>🧈 Graisses {compare(sug['fat_100g'],row['fat_100g'])}</div>
<div>🔥 Saturées {compare(sug['saturated_fat_100g'],row['saturated_fat_100g'])}</div>
<div>💪 Protéines {compare(sug['proteins_100g'],row['proteins_100g'])}</div>
<div>🌾 Fibres {compare(sug['fiber_100g'],row['fiber_100g'])}</div>

</div>
</div>

</div>
""",unsafe_allow_html=True)

    else:
        st.info("Aucune suggestion trouvée.")