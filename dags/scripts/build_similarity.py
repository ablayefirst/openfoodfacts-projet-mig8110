import pandas as pd
from sqlalchemy import create_engine, text
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATABASE_URL = "postgresql+psycopg://postgres:postgres123@postgres:5432/openfood_db"
print("DATABASE_URL utilisée = postgresql+psycopg://postgres:***@postgres:5432/openfood_db")

# =========================================================
# PARAMÈTRES DE GÉNÉRATION
#
# MODES DE SIMILARITÉ GÉNÉRÉS :
# - "meme_categorie"              : même catégorie principale
# - "profil_nutritionnel"         : proximité nutritionnelle
# - "score_nutritionnel_global"   : proximité NutriScore
# - "niveau_transformation_nova"  : proximité NOVA
#
# RECOMMANDATIONS GÉNÉRÉES :
# - "similaire"
# - "plus_saine"
#
# LOGIQUE FINALE :
# - similaires et plus saines sont indépendants
# - un produit peut être plus sain sans être retenu comme similaire
# =========================================================
SIMILARITY_MODES = [
    "meme_categorie",
    "profil_nutritionnel",
    "score_nutritionnel_global",
    "niveau_transformation_nova",
]

RECOMMENDATION_TYPES = [
    "similaire",
    "plus_saine"
]

# Seuils de filtrage
PROFILE_NUTRITIONNEL_MIN_SCORE = 0.35
SCORE_NUTRITIONNEL_GLOBAL_MIN_SCORE = 0.50
NIVEAU_TRANSFORMATION_NOVA_MIN_SCORE = 0.50

# Seuils santé
MIN_HEALTH_GAIN = 3.0
MIN_IMPROVEMENTS = 2

# ==============================
# 1. Charger produits
# ==============================

QUERY = """
SELECT
    p.code_produit,
    p.nom_produit,
    p.categorie_principale,
    p.nutrition_grade,
    p.nutriscore_score,
    p.nova_group,
    v.sugars_100g,
    v.salt_100g,
    v.saturated_fat_100g,
    v.fiber_100g,
    v.proteins_100g,
    v.carbohydrates_100g,
    v.fat_100g,
    COALESCE(string_agg(DISTINCT ing.ingredients_nom, ', '), '') AS ingredients_text
FROM produit p
LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
LEFT JOIN produit_ingredient pi ON p.code_produit = pi.code_produit
LEFT JOIN ingredient ing ON pi.id_ingredient = ing.id_ingredient
GROUP BY
    p.code_produit,
    p.nom_produit,
    p.categorie_principale,
    p.nutrition_grade,
    p.nutriscore_score,
    p.nova_group,
    v.sugars_100g,
    v.salt_100g,
    v.saturated_fat_100g,
    v.fiber_100g,
    v.proteins_100g,
    v.carbohydrates_100g,
    v.fat_100g
"""

# ==============================
# 2. Fonctions utilitaires
# ==============================

def safe_float(value, default=None):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=None):
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def nutriscore_value(grade):
    mapping = {
        "A": 5,
        "B": 4,
        "C": 3,
        "D": 2,
        "E": 1
    }
    return mapping.get(str(grade).upper(), 0)


def compute_health_score(sugar, salt, fat_sat, fiber, proteins, nova, nutriscore):
    """
    Score santé inspiré des recommandations OMS.

    Idée :
    - pénaliser fortement le sucre, le sel et les graisses saturées
    - récompenser les fibres
    - donner un petit bonus aux protéines
    - garder NOVA et NutriScore comme facteurs complémentaires

    Le score final est borné entre 0 et 100.
    Plus le score est élevé, plus le produit est considéré comme sain.
    """

    score = 100.0

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
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
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
    return round(score, 4)


def clean(text):
    if not text:
        return []

    text = str(text).lower().replace("(", ",").replace(")", ",")
    tokens = [t.strip() for t in text.split(",")]

    cleaned = []
    seen = set()

    for token in tokens:
        if len(token) > 2 and token not in seen:
            seen.add(token)
            cleaned.append(token)

    return cleaned


def jaccard_from_sets(a_set, b_set):
    if not (a_set | b_set):
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)


def similarity_method_label(mode):
    if mode == "meme_categorie":
        return "meme_categorie"
    if mode == "profil_nutritionnel":
        return "profil_nutritionnel"
    if mode == "score_nutritionnel_global":
        return "score_nutritionnel_global"
    if mode == "niveau_transformation_nova":
        return "niveau_transformation_nova"
    return "mode_inconnu"


def build_product_dict(row):
    return {
        "code_produit": row.code_produit,
        "nom_produit": row.nom_produit,
        "categorie_principale": row.categorie_principale,
        "nutrition_grade": row.nutrition_grade,
        "nutriscore_score": row.nutriscore_score,
        "nova_group": row.nova_group,
        "sugars_100g": row.sugars_100g,
        "salt_100g": row.salt_100g,
        "saturated_fat_100g": row.saturated_fat_100g,
        "fiber_100g": row.fiber_100g,
        "proteins_100g": row.proteins_100g,
        "carbohydrates_100g": row.carbohydrates_100g,
        "fat_100g": row.fat_100g,
        "health_score": row.health_score,
        "ingredients_text": row.ingredients_text,
        "ingredients_clean": row.ingredients_clean,
        "ingredients_set": row.ingredients_set,
        "doc": row.doc,
        "category_norm": row.category_norm,
    }


def category_similarity(a, b):
    a_cat = str(a["categorie_principale"]).strip().lower() if pd.notna(a["categorie_principale"]) else ""
    b_cat = str(b["categorie_principale"]).strip().lower() if pd.notna(b["categorie_principale"]) else ""

    if a_cat != "" and a_cat == b_cat:
        return 1.0
    return 0.0


def nutrition_similarity(a, b):
    a_sugar = safe_float(a["sugars_100g"], 0.0)
    b_sugar = safe_float(b["sugars_100g"], 0.0)

    a_salt = safe_float(a["salt_100g"], 0.0)
    b_salt = safe_float(b["salt_100g"], 0.0)

    a_sat = safe_float(a["saturated_fat_100g"], 0.0)
    b_sat = safe_float(b["saturated_fat_100g"], 0.0)

    a_fiber = safe_float(a["fiber_100g"], 0.0)
    b_fiber = safe_float(b["fiber_100g"], 0.0)

    a_protein = safe_float(a["proteins_100g"], 0.0)
    b_protein = safe_float(b["proteins_100g"], 0.0)

    distance = (
        abs(a_sugar - b_sugar) * 0.30 +
        abs(a_salt - b_salt) * 0.25 +
        abs(a_sat - b_sat) * 0.20 +
        abs(a_fiber - b_fiber) * 0.15 +
        abs(a_protein - b_protein) * 0.10
    )

    return round(1 / (1 + distance), 4)


def global_score_similarity(a, b):
    a_nutri = nutriscore_value(a["nutrition_grade"])
    b_nutri = nutriscore_value(b["nutrition_grade"])

    score = 1 - (abs(a_nutri - b_nutri) / 4)
    return round(max(0, score), 4)


def nova_similarity(a, b):
    a_nova = safe_int(a["nova_group"], 4)
    b_nova = safe_int(b["nova_group"], 4)

    score = 1 - (abs(a_nova - b_nova) / 3)
    return round(max(0, score), 4)


def compute_similarity_by_mode(a, b, mode):
    if mode == "meme_categorie":
        return category_similarity(a, b)

    if mode == "profil_nutritionnel":
        return nutrition_similarity(a, b)

    if mode == "score_nutritionnel_global":
        return global_score_similarity(a, b)

    if mode == "niveau_transformation_nova":
        return nova_similarity(a, b)

    return 0.0


def passes_similarity_threshold(mode, score):
    if mode == "meme_categorie":
        return score > 0

    if mode == "profil_nutritionnel":
        return score >= PROFILE_NUTRITIONNEL_MIN_SCORE

    if mode == "score_nutritionnel_global":
        return score >= SCORE_NUTRITIONNEL_GLOBAL_MIN_SCORE

    if mode == "niveau_transformation_nova":
        return score >= NIVEAU_TRANSFORMATION_NOVA_MIN_SCORE

    return False


def count_improvements(a, b):
    improvements = 0

    try:
        a_sugar = safe_float(a["sugars_100g"], None)
        b_sugar = safe_float(b["sugars_100g"], None)
        if a_sugar is not None and b_sugar is not None and b_sugar < a_sugar:
            improvements += 1
    except Exception:
        pass

    try:
        a_salt = safe_float(a["salt_100g"], None)
        b_salt = safe_float(b["salt_100g"], None)
        if a_salt is not None and b_salt is not None and b_salt < a_salt:
            improvements += 1
    except Exception:
        pass

    try:
        a_sat = safe_float(a["saturated_fat_100g"], None)
        b_sat = safe_float(b["saturated_fat_100g"], None)
        if a_sat is not None and b_sat is not None and b_sat < a_sat:
            improvements += 1
    except Exception:
        pass

    try:
        a_fiber = safe_float(a["fiber_100g"], None)
        b_fiber = safe_float(b["fiber_100g"], None)
        if a_fiber is not None and b_fiber is not None and b_fiber > a_fiber:
            improvements += 1
    except Exception:
        pass

    try:
        a_protein = safe_float(a["proteins_100g"], None)
        b_protein = safe_float(b["proteins_100g"], None)
        if a_protein is not None and b_protein is not None and b_protein > a_protein:
            improvements += 1
    except Exception:
        pass

    if nutriscore_value(b["nutrition_grade"]) > nutriscore_value(a["nutrition_grade"]):
        improvements += 1

    return improvements


def is_healthier(
    source_grade,
    target_grade,
    source_nova,
    target_nova,
    source_health_score,
    target_health_score,
    source_sugar=None,
    target_sugar=None,
    source_salt=None,
    target_salt=None,
    source_fat_sat=None,
    target_fat_sat=None,
    source_fiber=None,
    target_fiber=None,
    source_proteins=None,
    target_proteins=None,
):
    source_nutri = nutriscore_value(source_grade)
    target_nutri = nutriscore_value(target_grade)

    if target_nutri < source_nutri:
        return False

    try:
        if source_nova is not None and target_nova is not None:
            if int(target_nova) > int(source_nova):
                return False
    except Exception:
        pass

    if target_health_score <= source_health_score:
        return False

    try:
        if source_sugar is not None and target_sugar is not None:
            if pd.notna(source_sugar) and pd.notna(target_sugar):
                if float(target_sugar) > float(source_sugar) + 3:
                    return False
    except Exception:
        pass

    try:
        if source_salt is not None and target_salt is not None:
            if pd.notna(source_salt) and pd.notna(target_salt):
                if float(target_salt) > float(source_salt) + 0.2:
                    return False
    except Exception:
        pass

    try:
        if source_fat_sat is not None and target_fat_sat is not None:
            if pd.notna(source_fat_sat) and pd.notna(target_fat_sat):
                if float(target_fat_sat) > float(source_fat_sat) + 1:
                    return False
    except Exception:
        pass

    improvements = 0

    try:
        if source_sugar is not None and target_sugar is not None:
            if pd.notna(source_sugar) and pd.notna(target_sugar):
                if float(target_sugar) < float(source_sugar):
                    improvements += 1
    except Exception:
        pass

    try:
        if source_salt is not None and target_salt is not None:
            if pd.notna(source_salt) and pd.notna(target_salt):
                if float(target_salt) < float(source_salt):
                    improvements += 1
    except Exception:
        pass

    try:
        if source_fat_sat is not None and target_fat_sat is not None:
            if pd.notna(source_fat_sat) and pd.notna(target_fat_sat):
                if float(target_fat_sat) < float(source_fat_sat):
                    improvements += 1
    except Exception:
        pass

    try:
        if source_fiber is not None and target_fiber is not None:
            if pd.notna(source_fiber) and pd.notna(target_fiber):
                if float(target_fiber) > float(source_fiber):
                    improvements += 1
    except Exception:
        pass

    try:
        if source_proteins is not None and target_proteins is not None:
            if pd.notna(source_proteins) and pd.notna(target_proteins):
                if float(target_proteins) > float(source_proteins):
                    improvements += 1
    except Exception:
        pass

    if target_nutri > source_nutri:
        improvements += 1

    source_advantages = 0
    target_advantages = 0

    try:
        if source_sugar is not None and target_sugar is not None:
            if pd.notna(source_sugar) and pd.notna(target_sugar):
                if float(target_sugar) < float(source_sugar):
                    target_advantages += 1
                elif float(source_sugar) < float(target_sugar):
                    source_advantages += 1
    except Exception:
        pass

    try:
        if source_salt is not None and target_salt is not None:
            if pd.notna(source_salt) and pd.notna(target_salt):
                if float(target_salt) < float(source_salt):
                    target_advantages += 1
                elif float(source_salt) < float(target_salt):
                    source_advantages += 1
    except Exception:
        pass

    try:
        if source_fat_sat is not None and target_fat_sat is not None:
            if pd.notna(source_fat_sat) and pd.notna(target_fat_sat):
                if float(target_fat_sat) < float(source_fat_sat):
                    target_advantages += 1
                elif float(source_fat_sat) < float(target_fat_sat):
                    source_advantages += 1
    except Exception:
        pass

    try:
        if source_fiber is not None and target_fiber is not None:
            if pd.notna(source_fiber) and pd.notna(target_fiber):
                if float(target_fiber) > float(source_fiber):
                    target_advantages += 1
                elif float(source_fiber) > float(target_fiber):
                    source_advantages += 1
    except Exception:
        pass

    try:
        if source_proteins is not None and target_proteins is not None:
            if pd.notna(source_proteins) and pd.notna(target_proteins):
                if float(target_proteins) > float(source_proteins):
                    target_advantages += 1
                elif float(source_proteins) > float(target_proteins):
                    source_advantages += 1
    except Exception:
        pass

    if target_advantages >= 2 and source_advantages >= 2:
        return False

    if improvements < MIN_IMPROVEMENTS:
        return False

    if (target_health_score - source_health_score) < MIN_HEALTH_GAIN:
        return False

    return True


def is_healthier_by_mode(a, b, mode):
    try:
        if b["health_score"] <= a["health_score"]:
            return False

        if mode == "meme_categorie":
            if category_similarity(a, b) <= 0:
                return False

            if not is_healthier(
                a["nutrition_grade"],
                b["nutrition_grade"],
                a["nova_group"],
                b["nova_group"],
                a["health_score"],
                b["health_score"],
                a["sugars_100g"],
                b["sugars_100g"],
                a["salt_100g"],
                b["salt_100g"],
                a["saturated_fat_100g"],
                b["saturated_fat_100g"],
                a["fiber_100g"],
                b["fiber_100g"],
                a["proteins_100g"],
                b["proteins_100g"],
            ):
                return False

            return True

        elif mode == "profil_nutritionnel":
            improvements = count_improvements(a, b)

            if improvements < MIN_IMPROVEMENTS:
                return False

            if (b["health_score"] - a["health_score"]) < MIN_HEALTH_GAIN:
                return False

            return True

        elif mode == "score_nutritionnel_global":
            source_nutri = nutriscore_value(a["nutrition_grade"])
            target_nutri = nutriscore_value(b["nutrition_grade"])

            if target_nutri < source_nutri:
                return False

            if (b["health_score"] - a["health_score"]) < MIN_HEALTH_GAIN:
                return False

            return True

        elif mode == "niveau_transformation_nova":
            source_nova = safe_int(a["nova_group"], 4)
            target_nova = safe_int(b["nova_group"], 4)

            if target_nova > source_nova:
                return False

            if (b["health_score"] - a["health_score"]) < MIN_HEALTH_GAIN:
                return False

            return True

        return is_healthier(
            a["nutrition_grade"],
            b["nutrition_grade"],
            a["nova_group"],
            b["nova_group"],
            a["health_score"],
            b["health_score"],
            a["sugars_100g"],
            b["sugars_100g"],
            a["salt_100g"],
            b["salt_100g"],
            a["saturated_fat_100g"],
            b["saturated_fat_100g"],
            a["fiber_100g"],
            b["fiber_100g"],
            a["proteins_100g"],
            b["proteins_100g"],
        )

    except Exception:
        return False


def make_result_row(a, b, score, nb_commons, commons_sorted, methode, mode_sante, type_recommandation):
    return {
        "code_produit_source": a.code_produit,
        "code_produit_cible": b.code_produit,
        "score_similarite": round(float(score), 4),
        "nb_ingredients_communs": nb_commons,
        "ingredients_communs": ", ".join(commons_sorted[:8]),
        "methode": methode,
        "mode_sante": mode_sante,
        "type_recommandation": type_recommandation,
        "health_score_source": a.health_score,
        "health_score_cible": b.health_score
    }


def make_result_row_from_dict(a, b, score, nb_commons, commons_sorted, methode, mode_sante, type_recommandation):
    return {
        "code_produit_source": a["code_produit"],
        "code_produit_cible": b["code_produit"],
        "score_similarite": round(float(score), 4),
        "nb_ingredients_communs": nb_commons,
        "ingredients_communs": ", ".join(commons_sorted[:8]),
        "methode": methode,
        "mode_sante": mode_sante,
        "type_recommandation": type_recommandation,
        "health_score_source": a["health_score"],
        "health_score_cible": b["health_score"]
    }


# ==============================
# 3. Main
# ==============================

def main():
    engine = create_engine(DATABASE_URL)

    df = pd.read_sql(QUERY, engine)

    # ==============================
    # 4. Nettoyage des ingrédients
    # ==============================

    df["ingredients_clean"] = df["ingredients_text"].apply(clean)
    df["ingredients_set"] = df["ingredients_clean"].apply(set)
    df["doc"] = df["ingredients_clean"].apply(lambda x: " ".join(x))
    df["category_norm"] = df["categorie_principale"].apply(
        lambda x: str(x).strip().lower() if pd.notna(x) else ""
    )

    # Conserve TF-IDF / ingrédients dans le script
    vectorizer = TfidfVectorizer()
    try:
        X = vectorizer.fit_transform(df["doc"].fillna(""))
        sim_matrix = cosine_similarity(X)
    except Exception:
        sim_matrix = None

    df["health_score"] = df.apply(
        lambda row: compute_health_score(
            row["sugars_100g"],
            row["salt_100g"],
            row["saturated_fat_100g"],
            row["fiber_100g"],
            row["proteins_100g"],
            row["nova_group"],
            row["nutrition_grade"]
        ),
        axis=1
    )

    print("Produits utilisés :", len(df))
    print("Modes de similarité à générer :", SIMILARITY_MODES)
    print("Types de recommandation :", RECOMMENDATION_TYPES)

    rows = list(df.itertuples(index=False))
    rows_dict = [build_product_dict(r) for r in rows]
    n = len(rows)

    all_results = []

    # ==============================
    # 5. Boucle unique sur les paires
    # ==============================

    for i in range(n):
        a = rows[i]
        a_data = rows_dict[i]

        for j in range(n):
            if i == j:
                continue

            b = rows[j]
            b_data = rows_dict[j]

            same_category = (a.category_norm == b.category_norm)
            commons_set = a.ingredients_set & b.ingredients_set
            commons_sorted = sorted(commons_set)
            nb_commons = len(commons_sorted)
            jac = jaccard_from_sets(a.ingredients_set, b.ingredients_set)

            if sim_matrix is not None:
                try:
                    cos = float(sim_matrix[i, j])
                except Exception:
                    cos = 0.0
            else:
                cos = 0.0

            # ==================================
            # PARTIE A : RECOMMANDATIONS SIMILAIRES
            # ==================================

            # MODE 1 : MÊME CATÉGORIE
            score_meme_categorie = compute_similarity_by_mode(a_data, b_data, "meme_categorie")

            if passes_similarity_threshold("meme_categorie", score_meme_categorie):
                all_results.append(
                    make_result_row(
                        a=a,
                        b=b,
                        score=score_meme_categorie,
                        nb_commons=nb_commons,
                        commons_sorted=commons_sorted,
                        methode="meme_categorie",
                        mode_sante="meme_categorie",
                        type_recommandation="similaire"
                    )
                )

            # MODE 2 : PROFIL NUTRITIONNEL
            score_profil_nutritionnel = compute_similarity_by_mode(a_data, b_data, "profil_nutritionnel")

            if passes_similarity_threshold("profil_nutritionnel", score_profil_nutritionnel):
                all_results.append(
                    make_result_row(
                        a=a,
                        b=b,
                        score=score_profil_nutritionnel,
                        nb_commons=nb_commons,
                        commons_sorted=commons_sorted,
                        methode="profil_nutritionnel",
                        mode_sante="profil_nutritionnel",
                        type_recommandation="similaire"
                    )
                )

            # MODE 3 : SCORE NUTRITIONNEL GLOBAL
            score_score_nutritionnel_global = compute_similarity_by_mode(a_data, b_data, "score_nutritionnel_global")

            if passes_similarity_threshold("score_nutritionnel_global", score_score_nutritionnel_global):
                all_results.append(
                    make_result_row(
                        a=a,
                        b=b,
                        score=score_score_nutritionnel_global,
                        nb_commons=nb_commons,
                        commons_sorted=commons_sorted,
                        methode="score_nutritionnel_global",
                        mode_sante="score_nutritionnel_global",
                        type_recommandation="similaire"
                    )
                )

            # MODE 4 : NIVEAU DE TRANSFORMATION NOVA
            score_niveau_transformation_nova = compute_similarity_by_mode(a_data, b_data, "niveau_transformation_nova")

            if passes_similarity_threshold("niveau_transformation_nova", score_niveau_transformation_nova):
                all_results.append(
                    make_result_row(
                        a=a,
                        b=b,
                        score=score_niveau_transformation_nova,
                        nb_commons=nb_commons,
                        commons_sorted=commons_sorted,
                        methode="niveau_transformation_nova",
                        mode_sante="niveau_transformation_nova",
                        type_recommandation="similaire"
                    )
                )

            # ==================================
            # PARTIE B : RECOMMANDATIONS PLUS SAINES
            # ==================================
            # IMPORTANT :
            # elles sont indépendantes des recommandations "similaire"

            # MODE 1 : MÊME CATÉGORIE + plus saine
            score_meme_categorie_healthy = category_similarity(a_data, b_data)
            if is_healthier_by_mode(a_data, b_data, "meme_categorie"):
                all_results.append(
                    make_result_row(
                        a=a,
                        b=b,
                        score=score_meme_categorie_healthy,
                        nb_commons=nb_commons,
                        commons_sorted=commons_sorted,
                        methode="meme_categorie",
                        mode_sante="meme_categorie",
                        type_recommandation="plus_saine"
                    )
                )

            # MODE 2 : PROFIL NUTRITIONNEL + plus saine
            score_profil_nutritionnel_healthy = nutrition_similarity(a_data, b_data)
            if is_healthier_by_mode(a_data, b_data, "profil_nutritionnel"):
                all_results.append(
                    make_result_row(
                        a=a,
                        b=b,
                        score=score_profil_nutritionnel_healthy,
                        nb_commons=nb_commons,
                        commons_sorted=commons_sorted,
                        methode="profil_nutritionnel",
                        mode_sante="profil_nutritionnel",
                        type_recommandation="plus_saine"
                    )
                )

            # MODE 3 : SCORE NUTRITIONNEL GLOBAL + plus saine
            score_score_nutritionnel_global_healthy = global_score_similarity(a_data, b_data)
            if is_healthier_by_mode(a_data, b_data, "score_nutritionnel_global"):
                all_results.append(
                    make_result_row(
                        a=a,
                        b=b,
                        score=score_score_nutritionnel_global_healthy,
                        nb_commons=nb_commons,
                        commons_sorted=commons_sorted,
                        methode="score_nutritionnel_global",
                        mode_sante="score_nutritionnel_global",
                        type_recommandation="plus_saine"
                    )
                )

            # MODE 4 : NIVEAU DE TRANSFORMATION NOVA + plus saine
            score_niveau_transformation_nova_healthy = nova_similarity(a_data, b_data)
            if is_healthier_by_mode(a_data, b_data, "niveau_transformation_nova"):
                all_results.append(
                    make_result_row(
                        a=a,
                        b=b,
                        score=score_niveau_transformation_nova_healthy,
                        nb_commons=nb_commons,
                        commons_sorted=commons_sorted,
                        methode="niveau_transformation_nova",
                        mode_sante="niveau_transformation_nova",
                        type_recommandation="plus_saine"
                    )
                )

    # ==============================
    # 6. Création DataFrame
    # ==============================

    if all_results:
        result_df = pd.DataFrame(all_results)
    else:
        result_df = pd.DataFrame(columns=[
            "code_produit_source",
            "code_produit_cible",
            "score_similarite",
            "nb_ingredients_communs",
            "ingredients_communs",
            "methode",
            "mode_sante",
            "type_recommandation",
            "health_score_source",
            "health_score_cible"
        ])

    # ==============================
    # 7. Suppression doublons éventuels
    # ==============================

    if not result_df.empty:
        result_df = result_df.drop_duplicates(
            subset=[
                "code_produit_source",
                "code_produit_cible",
                "methode",
                "mode_sante",
                "type_recommandation"
            ]
        ).reset_index(drop=True)

    # ==============================
    # 8. Top 5 par source / méthode / mode_sante / type
    # ==============================

    if not result_df.empty:
        result_df = result_df.sort_values(
            ["code_produit_source", "methode", "mode_sante", "type_recommandation", "score_similarite"],
            ascending=[True, True, True, True, False]
        )

        result_df = (
            result_df
            .groupby(
                ["code_produit_source", "methode", "mode_sante", "type_recommandation"],
                as_index=False,
                group_keys=False
            )
            .head(5)
            .reset_index(drop=True)
        )

    # ==============================
    # 9. Logs de synthèse
    # ==============================

    print("===================================================")
    print("SYNTHÈSE PAR MODE")
    print("===================================================")

    for sim_mode in SIMILARITY_MODES:
        label_sim = similarity_method_label(sim_mode)

        sim_count_final = 0
        healthy_count_final = 0

        if not result_df.empty:
            sim_count_final = len(result_df[
                (result_df["methode"] == label_sim) &
                (result_df["type_recommandation"] == "similaire")
            ])

            healthy_count_final = len(result_df[
                (result_df["methode"] == label_sim) &
                (result_df["type_recommandation"] == "plus_saine")
            ])

        print(f"[{sim_mode}] Similaires retenus : {sim_count_final}")
        print(f"[{sim_mode}] Plus saines retenues : {healthy_count_final}")

    print("Total final inséré :", len(result_df))

    # ==============================
    # 10. Aperçu
    # ==============================

    print("Colonnes result_df :", result_df.columns.tolist())
    if not result_df.empty:
        print(result_df[[
            "code_produit_source",
            "code_produit_cible",
            "methode",
            "mode_sante",
            "type_recommandation",
            "health_score_source",
            "health_score_cible"
        ]].head(20))

    # ==============================
    # 11. Insertion en base
    # ==============================

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM produit_similaire"))
        if not result_df.empty:
            result_df.to_sql("produit_similaire", conn, if_exists="append", index=False)

    print("✅ Recommandations similaires et plus saines enregistrées en base")
    print("✅ Modes générés :", ", ".join([similarity_method_label(m) for m in SIMILARITY_MODES]))


if __name__ == "__main__":
    main()