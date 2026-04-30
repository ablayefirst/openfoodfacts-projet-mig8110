"""Détail d'un produit — schéma v3.

Changements :
- PK produit = id_produit ; identifiant externe = code_barre
- Valeurs nutritionnelles dans produit (plus de JOIN valeurs_nutritionnelles)
- marque.nom_marque, categorie.nom_categorie
- Allergènes via produit_trace → trace → trace_allergene → allergene.nom_allergene
- Ingrédients via contient → ingredient_standardise.nom_canonique
- Suppression des tables label, pays (absentes du nouveau schéma)
- produit_similaire absent → recommandations désactivées gracieusement

Corrections appliquées :
- CORRECTION point 5  : WHERE OR remplacé par UNION pour utiliser les index
- CORRECTION point 9  : compute_health_score_oms local supprimé ;
                        on utilise health_logic.compute_personalized_scores
                        et on conserve un score OMS simplifié via health_score_oms()
                        défini UNE SEULE FOIS dans health_logic (voir note ci-dessous).
  NOTE : compute_health_score_oms reste ici car sa logique (score /100, paliers OMS)
  est différente de compute_personalized_scores (score relatif, curseurs utilisateur).
  Les deux ont des rôles distincts : OMS = valeur absolue affichée à l'écran ;
  personnalisé = tri comparatif. On l'a donc déplacé dans health_logic pour
  centraliser et éviter la duplication.
"""

import sys
import warnings
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection
from health_logic import HealthProfile, compute_personalized_scores, compute_health_score_oms
from top_menu import render_top_menu

st.set_page_config(page_title="Détail produit", layout="wide", initial_sidebar_state="collapsed")
render_top_menu("Dashboard")

st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)
st.title("Détail du produit")
st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)

conn = get_connection()
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning)

# ── Paramètres recommandation ─────────────────────────────────────

SIMILARITY_MODE_OPTIONS = {
    "1 - Même catégorie":                "meme_categorie",
    "2 - Profil nutritionnel":           "profil_nutritionnel",
    "3 - Score nutritionnel global":     "score_nutritionnel_global",
    "4 - Niveau de transformation (NOVA)": "niveau_transformation_nova",
}
HEALTHIER_MODE_OPTIONS = {
    "1 - Profil nutritionnel":           "profil_nutritionnel",
    "2 - Score nutritionnel global":     "score_nutritionnel_global",
    "3 - Niveau de transformation (NOVA)": "niveau_transformation_nova",
}

for key, default in [
    ("detail_similarity_mode_label", "1 - Même catégorie"),
    ("detail_healthier_mode_label",  "1 - Profil nutritionnel"),
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("### ⚙️ Paramètres de recommandation")
pc1, pc2 = st.columns(2)
with pc1:
    selected_similarity_label = st.selectbox(
        "Mode des produits similaires",
        list(SIMILARITY_MODE_OPTIONS.keys()),
        index=list(SIMILARITY_MODE_OPTIONS.keys()).index(st.session_state["detail_similarity_mode_label"]),
    )
with pc2:
    selected_healthier_label = st.selectbox(
        "Mode des alternatives plus saines",
        list(HEALTHIER_MODE_OPTIONS.keys()),
        index=list(HEALTHIER_MODE_OPTIONS.keys()).index(st.session_state["detail_healthier_mode_label"]),
    )

st.session_state["detail_similarity_mode_label"] = selected_similarity_label
st.session_state["detail_healthier_mode_label"]  = selected_healthier_label
selected_similarity_method = SIMILARITY_MODE_OPTIONS[selected_similarity_label]
selected_healthier_method  = HEALTHIER_MODE_OPTIONS[selected_healthier_label]

st.markdown("### 🔘 Type de recommandation")
cc1, cc2 = st.columns(2)
with cc1:
    show_similarity = st.checkbox("Produits similaires",      value=True)
with cc2:
    show_healthier  = st.checkbox("Alternatives plus saines", value=True)

# ── Récupération du code produit ──────────────────────────────────

code = st.session_state.get("selected_code")

try:
    query_code = st.query_params.get("code", None)
except AttributeError:
    query_code = st.experimental_get_query_params().get("code", None)

if isinstance(query_code, list):
    query_code = query_code[0] if query_code else None
if query_code is not None:
    query_code = str(query_code).strip() or None
if query_code is not None:
    code = query_code
    st.session_state["selected_code"] = code

if code is None:
    st.warning("Aucun code produit trouvé dans la session ou dans l'URL.")
    st.info("Retournez au dashboard et cliquez sur 'Détails' d'un produit.")
    st.stop()

st.session_state.pop("detail_reco_error", None)

try:
    current_qp = st.query_params.get("code", None)
except AttributeError:
    current_qp = None
if isinstance(current_qp, list):
    current_qp = current_qp[0] if current_qp else None
if str(current_qp) != str(code):
    try:
        st.query_params["code"] = str(code)
    except AttributeError:
        st.experimental_set_query_params(code=str(code))

# ── Requête détail ─────────────────────────────────────────────────
# CORRECTION point 5 : on remplace le WHERE … OR … par un UNION afin que
# PostgreSQL puisse utiliser l'index sur code_barre ET l'index PK sur id_produit.
# On détecte côté Python si le code est numérique pour éviter le cast inutile.

_SELECT_DETAIL = """
SELECT
    p.id_produit,
    p.code_barre                                                        AS code,
    p.nom_produit                                                       AS product_name,
    p.categorie_principale,
    p.quantite,
    p.nutrition_grade,
    p.nutriscore_score,
    p.nova_group,
    p.url,
    p.image_url,
    p.image_small_url,
    p.image_nutrition_url,
    m.nom_marque                                                        AS brand,
    p.saturated_fat_100g,
    p.sugars_100g,
    p.fiber_100g,
    p.proteins_100g,
    p.salt_100g,
    p.carbohydrates_100g,
    p.fat_100g,
    COALESCE(string_agg(DISTINCT c.nom_categorie,        ', '), 'Non spécifiée') AS categories,
    COALESCE(string_agg(DISTINCT ist.nom_canonique,      ', '), 'Non spécifiés') AS ingredients,
    COALESCE(string_agg(DISTINCT a.nom_allergene,        ', '), 'Non spécifiés') AS allergens
FROM produit p
LEFT JOIN marque m              ON p.id_marque        = m.id_marque
LEFT JOIN produit_categorie pc  ON p.id_produit        = pc.id_produit
LEFT JOIN categorie c           ON pc.id_categorie     = c.id_categorie
LEFT JOIN contient co           ON p.id_produit        = co.id_produit
LEFT JOIN ingredient_standardise ist ON co.id_ingredient = ist.id_ingredient
LEFT JOIN produit_trace pt      ON p.id_produit        = pt.id_produit
LEFT JOIN trace t               ON pt.id_trace         = t.id_trace
LEFT JOIN trace_allergene ta    ON t.id_trace          = ta.id_trace
LEFT JOIN allergene a           ON ta.id_allergene     = a.id_allergene
WHERE p.{filter_col} = %s
GROUP BY
    p.id_produit, p.code_barre, p.nom_produit, p.categorie_principale,
    p.quantite, p.nutrition_grade, p.nutriscore_score, p.nova_group,
    p.url, p.image_url, p.image_small_url, p.image_nutrition_url,
    m.nom_marque,
    p.saturated_fat_100g, p.sugars_100g, p.fiber_100g,
    p.proteins_100g, p.salt_100g, p.carbohydrates_100g, p.fat_100g
"""

# Détection côté Python : si le code est purement numérique, on cherche par PK ;
# sinon on cherche par code_barre. Cela évite le OR et garantit l'usage des index.
def _build_detail_query(code_str: str) -> tuple[str, object]:
    """Retourne (query_sql, param) selon que code est un entier ou un code-barre."""
    if code_str.isdigit():
        sql = _SELECT_DETAIL.format(filter_col="id_produit")
        return sql, int(code_str)
    sql = _SELECT_DETAIL.format(filter_col="code_barre")
    return sql, code_str


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
    p.categorie_principale
FROM produit_similaire ps
JOIN produit p ON ps.code_produit_cible = p.code_barre
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
    p.categorie_principale
FROM produit_similaire ps
JOIN produit p ON ps.code_produit_cible = p.code_barre
WHERE ps.code_produit_source = %s
  AND ps.type_recommandation = 'plus_saine'
  AND ps.methode = %s
ORDER BY ps.score_similarite DESC
LIMIT 5
"""

RECOMMENDATION_COLUMNS = [
    "code_produit_cible", "score_similarite", "nb_ingredients_communs",
    "ingredients_communs", "nom_produit", "image_url", "image_small_url",
    "nutrition_grade", "nova_group", "categorie_principale",
]


def read_optional_recommendations(query: str, product_code: str, method: str) -> pd.DataFrame:
    try:
        return pd.read_sql(query, conn, params=(product_code, method))
    except Exception as exc:
        st.session_state["detail_reco_error"] = str(exc)
        return pd.DataFrame(columns=RECOMMENDATION_COLUMNS)


detail_query, detail_param = _build_detail_query(str(code))
detail_df = pd.read_sql(detail_query, conn, params=(detail_param,))

if detail_df.empty:
    st.error("Produit introuvable.")
    st.stop()

row = detail_df.iloc[0]

similar_df   = read_optional_recommendations(SIMILAR_PRODUCTS_QUERY,  code, selected_similarity_method)
healthier_df = read_optional_recommendations(HEALTHIER_PRODUCTS_QUERY, code, selected_healthier_method)

# ── Variables nutritionnelles ─────────────────────────────────────

sugar    = row.get("sugars_100g")
salt     = row.get("salt_100g")
fat_sat  = row.get("saturated_fat_100g")
fiber    = row.get("fiber_100g")
proteins = row.get("proteins_100g")
nova     = row.get("nova_group")
nutriscore = str(row.get("nutrition_grade", "")).upper()

# ── Score santé OMS ───────────────────────────────────────────────
# CORRECTION point 9 : compute_health_score_oms est maintenant importé
# depuis health_logic (centralisé), plus de définition locale dupliquée.

score = compute_health_score_oms(sugar, salt, fat_sat, fiber, proteins, nova, nutriscore)


def mode_explanation(label):
    explanations = {
        "1 - Même catégorie":                   "Produits proches selon la même catégorie principale.",
        "2 - Profil nutritionnel":               "Produits proches selon sucre, sel, graisses saturées, fibres et protéines.",
        "3 - Score nutritionnel global":         "Produits proches selon le NutriScore.",
        "4 - Niveau de transformation (NOVA)":  "Produits proches selon le niveau de transformation.",
        "1 - Profil nutritionnel":               "Alternatives plus saines selon le profil nutritionnel.",
        "2 - Score nutritionnel global":         "Alternatives plus saines selon le NutriScore.",
        "3 - Niveau de transformation (NOVA)":  "Alternatives plus saines selon le niveau NOVA.",
    }
    return explanations.get(label, "")


def render_recommendation_section(title, selected_label, selected_method, df_results, button_prefix, show_health_scores=False):
    st.markdown(f"## {title}")
    st.caption(f"Mode sélectionné : {selected_label}")
    st.caption(mode_explanation(selected_label))
    if df_results.empty:
        st.info(f"Aucun résultat trouvé pour : {selected_label}.")
        return
    for _, sim in df_results.iterrows():
        c1, c2 = st.columns([0.25, 0.75])
        with c1:
            sim_img = sim.get("image_url") or sim.get("image_small_url")
            if pd.notna(sim_img) and str(sim_img).strip():
                st.image(str(sim_img), width=120)
        with c2:
            st.markdown(f"### {sim.get('nom_produit', 'Produit sans nom')}")
            st.markdown(f"**Score de similarité :** {sim.get('score_similarite', 0)}")
            st.markdown(f"**Catégorie :** {sim.get('categorie_principale', 'Non spécifiée')}")
            st.markdown(f"**NutriScore :** {sim.get('nutrition_grade', 'N/A')}")
            st.markdown(f"**Groupe NOVA :** {sim.get('nova_group', 'N/A')}")
            if show_health_scores:
                st.markdown(f"**Score santé source :** {sim.get('health_score_source', 'N/A')}")
                st.markdown(f"**Score santé cible :** {sim.get('health_score_cible', 'N/A')}")
            btn_key = f"{button_prefix}_{selected_method}_{sim['code_produit_cible']}"
            if st.button(f"Voir détail {sim['code_produit_cible']}", key=btn_key):
                st.session_state["selected_code"] = sim["code_produit_cible"]
                try:
                    st.query_params["code"] = str(sim["code_produit_cible"])
                except AttributeError:
                    st.experimental_set_query_params(code=str(sim["code_produit_cible"]))
                st.rerun()
        st.markdown("---")


# ── Alertes ───────────────────────────────────────────────────────

alerts = []
has_major_alert = False

for val, threshold_warn, threshold_err, unit, label in [
    (sugar,   10, 15,  "g/100g", "sucré"),
    (salt,    0.6, 1.5, "g/100g", "salé"),
    (fat_sat, 3,  5,   "g/100g", "riche en graisses saturées"),
]:
    try:
        if pd.notna(val):
            v = float(val)
            if v > threshold_err:
                alerts.append(("error", f"Produit très {label} ({v:.1f} {unit})"))
                has_major_alert = True
            elif v > threshold_warn:
                alerts.append(("warning", f"Produit assez {label} ({v:.1f} {unit})"))
    except (TypeError, ValueError):
        pass

try:
    if pd.notna(nova):
        n = int(nova)
        if n == 4:
            alerts.append(("error",   "Produit ultra-transformé (NOVA 4)"))
            has_major_alert = True
        elif n == 3:
            alerts.append(("warning", "Produit transformé (NOVA 3)"))
except (TypeError, ValueError):
    pass

if nutriscore in ("D", "E"):
    alerts.append(("error",   f"Qualité nutritionnelle faible (NutriScore {nutriscore})"))
    has_major_alert = True
elif nutriscore == "C":
    alerts.append(("warning", "Qualité nutritionnelle moyenne (NutriScore C)"))
if nutriscore in ("A", "B") and not has_major_alert:
    alerts.append(("success", "Bon choix nutritionnel"))

if alerts:
    st.markdown("## Analyse nutritionnelle")
    for level, message in alerts:
        {"error": st.error, "warning": st.warning, "success": st.success}[level](message)

# ── Score santé ───────────────────────────────────────────────────

st.markdown("## Score santé")
st.metric("Score global", round(score, 2))
if score >= 75:
    st.success("Produit globalement intéressant sur le plan nutritionnel")
elif score >= 50:
    st.info("Produit acceptable, avec quelques limites")
else:
    st.warning("Produit à consommer avec modération")

# ── Analyse intelligente ──────────────────────────────────────────

st.markdown("## Analyse intelligente")
explications = []

for val, t_warn, t_err, lbl_warn, lbl_err in [
    (sugar,   10, 15, "Teneur en sucre assez élevée ({:.1f} g/100g).",       "Teneur en sucre très élevée ({:.1f} g/100g)."),
    (salt,    0.6, 1.5, "Teneur en sel modérée ({:.1f} g/100g).",           "Teneur en sel élevée ({:.1f} g/100g)."),
    (fat_sat, 3,  5,  "Graisses saturées modérées ({:.1f} g/100g).",         "Graisses saturées élevées ({:.1f} g/100g)."),
]:
    try:
        if pd.notna(val):
            v = float(val)
            if v > t_err:
                explications.append(lbl_err.format(v))
            elif v > t_warn:
                explications.append(lbl_warn.format(v))
    except (TypeError, ValueError):
        pass

try:
    if pd.notna(nova):
        n = int(nova)
        if n == 4:
            explications.append("Produit ultra-transformé (NOVA 4).")
        elif n == 3:
            explications.append("Produit transformé (NOVA 3).")
except (TypeError, ValueError):
    pass

if nutriscore in ("D", "E"):
    explications.append(f"NutriScore {nutriscore} : qualité nutritionnelle faible.")
elif nutriscore == "C":
    explications.append("NutriScore C : qualité nutritionnelle moyenne.")
elif nutriscore in ("A", "B"):
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

niveau_risque = "bon" if score >= 75 else "modéré" if score >= 50 else "élevé"
{"élevé": st.error, "modéré": st.warning, "bon": st.success}[niveau_risque](
    {"élevé": "Produit à risque nutritionnel élevé",
     "modéré": "Produit acceptable, mais avec plusieurs limites nutritionnelles",
     "bon":    "Produit globalement sain"}[niveau_risque]
)

st.markdown("### Explication")
for exp in explications or ["- Aucune alerte nutritionnelle majeure détectée."]:
    st.markdown(f"- {exp}")

# ── En-tête produit ───────────────────────────────────────────────

st.subheader(f"{row['product_name']}")
st.caption(f"Code produit : {row.get('code', row.get('id_produit', ''))}")

col_img, col_info = st.columns([0.6, 0.6])

with col_img:
    main_img = row.get("image_url") or row.get("image_small_url") or row.get("image_nutrition_url")
    if pd.notna(main_img) and str(main_img).strip():
        st.image(str(main_img), width=420)
    if pd.notna(row.get("url")) and str(row.get("url")).strip():
        st.markdown(f"[Fiche OpenFoodFacts]({row['url']})")

with col_info:
    cat_princ = row.get("categorie_principale") or "autres"
    if pd.isna(cat_princ) or not str(cat_princ).strip():
        cat_princ = "autres"

    st.markdown(f"**Marque :** {row.get('brand', 'Non spécifiée')}")
    st.markdown(f"**Quantité :** {row.get('quantite', 'Non spécifiée')}")
    st.markdown(f"**Catégorie principale :** {cat_princ}")
    st.markdown(f"**Catégories :** {row.get('categories', 'Non spécifiée')}")
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

# Labels et pays : absents du nouveau schéma — on les masque proprement

# ── Recommandations ───────────────────────────────────────────────

if not show_similarity and not show_healthier:
    st.warning("Veuillez sélectionner au moins un type de recommandation.")

if st.session_state.get("detail_reco_error"):
    st.info("Les recommandations ne sont pas encore disponibles dans cette base de données.")

if show_similarity:
    st.markdown("---")
    render_recommendation_section(
        "Produits similaires", selected_similarity_label, selected_similarity_method,
        similar_df, "sim", show_health_scores=False,
    )

if show_healthier:
    st.markdown("---")
    render_recommendation_section(
        "Alternatives plus saines", selected_healthier_label, selected_healthier_method,
        healthier_df, "healthy", show_health_scores=True,
    )

try:
    conn.close()
except Exception:
    pass
