import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import warnings

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection

st.set_page_config(page_title="Détail produit", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] {display: none;}
    </style>
    """,
    unsafe_allow_html=True,
)

if st.button("Retour au Dashboard"):
    st.switch_page("main.py")

st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)

st.title("Détail du produit")

st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)

conn = get_connection()

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

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
    st.info("Retournez au dashboard et cliquez sur le bouton 'Détails' d'un produit.")
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

# ==============================
# REQUÊTES SQL
# ==============================

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
    p.nom_produit,
    p.image_url,
    p.image_small_url,
    p.nutrition_grade,
    p.nova_group,
    p.categorie_principale
FROM produit_similaire ps
JOIN produit p
    ON ps.code_produit_cible = p.code_produit
WHERE ps.code_produit_source = %s
  AND ps.type_recommandation = 'similaire'
ORDER BY ps.score_similarite DESC
LIMIT 5
"""

HEALTHIER_PRODUCTS_QUERY = """
SELECT
    ps.code_produit_cible,
    ps.score_similarite,
    ps.nb_ingredients_communs,
    ps.ingredients_communs,
    p.nom_produit,
    p.image_url,
    p.image_small_url,
    p.nutrition_grade,
    p.nova_group,
    p.categorie_principale
FROM produit_similaire ps
JOIN produit p
    ON ps.code_produit_cible = p.code_produit
WHERE ps.code_produit_source = %s
  AND ps.type_recommandation = 'plus_saine'
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
]


def read_optional_recommendations(query: str, product_code: str) -> pd.DataFrame:
    """Load optional recommendation data without breaking the detail page.

    The recommendations table is populated by a separate process and may not
    exist yet in some environments. In that case we keep the page usable and
    simply return an empty result.
    """

    try:
        return pd.read_sql(query, conn, params=(product_code,))
    except Exception as exc:
        st.session_state["detail_reco_error"] = str(exc)
        return pd.DataFrame(columns=RECOMMENDATION_COLUMNS)

detail_df = pd.read_sql(DETAIL_QUERY, conn, params=(code,))

if detail_df.empty:
    st.error("Produit introuvable.")
    st.stop()

row = detail_df.iloc[0]

similar_df = read_optional_recommendations(SIMILAR_PRODUCTS_QUERY, code)
healthier_df = read_optional_recommendations(HEALTHIER_PRODUCTS_QUERY, code)

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

    # Références utilisées pour guider le scoring
    WHO_SUGAR_IDEAL = 25.0
    WHO_SUGAR_MAX = 50.0
    WHO_SALT_MAX = 5.0
    WHO_SAT_FAT_MAX = 22.0
    WHO_FIBER_MIN = 25.0

    # ----------------------------
    # 1. Pénalité sucre
    # ----------------------------
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

    # ----------------------------
    # 2. Pénalité sel
    # ----------------------------
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

    # ----------------------------
    # 3. Pénalité graisses saturées
    # ----------------------------
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

    # ----------------------------
    # 4. Bonus fibres
    # ----------------------------
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

    # ----------------------------
    # 5. Bonus protéines
    # ----------------------------
    try:
        if proteins is not None and pd.notna(proteins):
            proteins = float(proteins)

            if proteins >= 10:
                score += 4
            elif proteins >= 5:
                score += 2
    except (TypeError, ValueError):
        pass

    # ----------------------------
    # 6. Ajustement NOVA
    # ----------------------------
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

    # ----------------------------
    # 7. Ajustement NutriScore
    # ----------------------------
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


# ==============================
# 🚨 SYSTÈME D’ALERTES
# ==============================

alerts = []
has_major_alert = False

try:
    if pd.notna(sugar) and float(sugar) > 15:
        alerts.append(("error", f"⚠️ Produit très sucré ({float(sugar):.1f} g/100g)"))
        has_major_alert = True
    elif pd.notna(sugar) and float(sugar) > 10:
        alerts.append(("warning", f"⚠️ Produit assez sucré ({float(sugar):.1f} g/100g)"))
except (TypeError, ValueError) as e:
    st.error(f"Erreur lors de la vérification du sucre : {e}")

try:
    if pd.notna(salt) and float(salt) > 1.5:
        alerts.append(("error", f"⚠️ Produit très salé ({float(salt):.1f} g/100g)"))
        has_major_alert = True
    elif pd.notna(salt) and float(salt) > 0.6:
        alerts.append(("warning", f"⚠️ Produit assez salé ({float(salt):.1f} g/100g)"))
except (TypeError, ValueError) as e:
    st.error(f"Erreur lors de la vérification du sel : {e}")

try:
    if pd.notna(fat_sat) and float(fat_sat) > 5:
        alerts.append(("warning", f"⚠️ Riche en graisses saturées ({float(fat_sat):.1f} g/100g)"))
        has_major_alert = True
    elif pd.notna(fat_sat) and float(fat_sat) > 3:
        alerts.append(("warning", f"⚠️ Graisses saturées modérées ({float(fat_sat):.1f} g/100g)"))
except (TypeError, ValueError):
    pass

try:
    if pd.notna(nova) and int(nova) == 4:
        alerts.append(("error", "⚠️ Produit ultra-transformé (NOVA 4)"))
        has_major_alert = True
    elif pd.notna(nova) and int(nova) == 3:
        alerts.append(("warning", "⚠️ Produit transformé (NOVA 3)"))
except (TypeError, ValueError):
    pass

if nutriscore in ["D", "E"]:
    alerts.append(("error", f"⚠️ Qualité nutritionnelle faible (NutriScore {nutriscore})"))
    has_major_alert = True
elif nutriscore == "C":
    alerts.append(("warning", "⚠️ Qualité nutritionnelle moyenne (NutriScore C)"))

if nutriscore in ["A", "B"] and not has_major_alert:
    alerts.append(("success", "✅ Bon choix nutritionnel"))

# ==============================
# AFFICHAGE ALERTES
# ==============================

if alerts:
    st.markdown("## 🚨 Analyse nutritionnelle")

    for level, message in alerts:
        if level == "error":
            st.error(message)
        elif level == "warning":
            st.warning(message)
        elif level == "success":
            st.success(message)

# ==============================
# 💚 SCORE SANTÉ
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

st.markdown("## 💚 Score santé")
st.metric("Score global", round(score, 2))

if score >= 75:
    st.success("✅ Produit globalement intéressant sur le plan nutritionnel")
elif score >= 50:
    st.info("ℹ️ Produit acceptable, avec quelques limites")
else:
    st.warning("⚠️ Produit à consommer avec modération")

# ==============================
# 🧠 ANALYSE INTELLIGENTE
# ==============================

st.markdown("## 🧠 Analyse intelligente")

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

# Décision finale basée sur le score uniquement
if score >= 75:
    niveau_risque = "bon"
elif score >= 50:
    niveau_risque = "modéré"
else:
    niveau_risque = "élevé"

if niveau_risque == "élevé":
    st.error("🔴 Produit à risque nutritionnel élevé")
elif niveau_risque == "modéré":
    st.warning("🟠 Produit acceptable, mais avec plusieurs limites nutritionnelles")
else:
    st.success("🟢 Produit globalement sain")

st.markdown("### 📌 Explication")

if explications:
    for exp in explications:
        st.markdown(f"- {exp}")
else:
    st.markdown("- Aucune alerte nutritionnelle majeure détectée.")

# ==============================
# EN-TÊTE PRODUIT
# ==============================

col_title = st.columns([0.8, 0.2])[0]

with col_title:
    st.subheader(f"{row['product_name']}")
    st.caption(f"Code produit : {row['code']}")

# ==============================
# AFFICHAGE PRINCIPAL
# ==============================

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

# ==============================
# PRODUITS SIMILAIRES
# ==============================

st.markdown("---")
st.markdown("## 🔍 Produits similaires")
st.caption("Produits proches en composition et en catégorie.")

if st.session_state.get("detail_reco_error"):
    st.info("Les recommandations similaires ne sont pas encore disponibles dans cette base de données.")

if similar_df.empty:
    st.info("Aucun produit similaire trouvé.")
else:
    for _, sim in similar_df.iterrows():
        col1, col2 = st.columns([0.25, 0.75])

        with col1:
            sim_img = sim.get("image_url") or sim.get("image_small_url")
            if pd.notna(sim_img) and str(sim_img).strip() != "":
                st.image(str(sim_img), width=120)

        with col2:
            st.markdown(f"### {sim.get('nom_produit', 'Produit sans nom')}")
            st.markdown(f"**Score de similarité :** {sim.get('score_similarite', 0)}")
            st.markdown(f"**Catégorie :** {sim.get('categorie_principale', 'Non spécifiée')}")
            st.markdown(f"**NutriScore :** {sim.get('nutrition_grade', 'N/A')}")
            st.markdown(f"**Groupe NOVA :** {sim.get('nova_group', 'N/A')}")
            st.markdown(f"**Ingrédients communs :** {sim.get('ingredients_communs', 'Aucun')}")
            st.markdown(f"**Nombre d’ingrédients communs :** {sim.get('nb_ingredients_communs', 0)}")

            if st.button(
                f"Voir détail similaire {sim['code_produit_cible']}",
                key=f"sim_{sim['code_produit_cible']}"
            ):
                st.session_state["selected_code"] = sim["code_produit_cible"]
                try:
                    st.query_params["code"] = str(sim["code_produit_cible"])
                except AttributeError:
                    st.experimental_set_query_params(code=str(sim["code_produit_cible"]))
                st.rerun()

        st.markdown("---")

# ==============================
# ALTERNATIVES PLUS SAINES
# ==============================

st.markdown("## 🥗 Alternatives plus saines")
st.caption("Produits proches en composition, avec une qualité nutritionnelle meilleure ou équivalente.")

if healthier_df.empty:
    st.info("Aucune alternative plus saine trouvée.")
else:
    for _, sim in healthier_df.iterrows():
        col1, col2 = st.columns([0.25, 0.75])

        with col1:
            sim_img = sim.get("image_url") or sim.get("image_small_url")
            if pd.notna(sim_img) and str(sim_img).strip() != "":
                st.image(str(sim_img), width=120)

        with col2:
            st.markdown(f"### {sim.get('nom_produit', 'Produit sans nom')}")
            st.markdown(f"**Score de similarité :** {sim.get('score_similarite', 0)}")
            st.markdown(f"**Catégorie :** {sim.get('categorie_principale', 'Non spécifiée')}")
            st.markdown(f"**NutriScore :** {sim.get('nutrition_grade', 'N/A')}")
            st.markdown(f"**Groupe NOVA :** {sim.get('nova_group', 'N/A')}")
            st.markdown(f"**Ingrédients communs :** {sim.get('ingredients_communs', 'Aucun')}")
            st.markdown(f"**Nombre d’ingrédients communs :** {sim.get('nb_ingredients_communs', 0)}")

            if st.button(
                f"Voir détail sain {sim['code_produit_cible']}",
                key=f"healthy_{sim['code_produit_cible']}"
            ):
                st.session_state["selected_code"] = sim["code_produit_cible"]
                try:
                    st.query_params["code"] = str(sim["code_produit_cible"])
                except AttributeError:
                    st.experimental_set_query_params(code=str(sim["code_produit_cible"]))
                st.rerun()

        st.markdown("---")

try:
    conn.close()
except Exception:
    pass
