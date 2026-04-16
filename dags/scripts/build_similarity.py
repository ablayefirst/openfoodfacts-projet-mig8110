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
# - "ingredients" : similarité basée sur les ingrédients (Jaccard)
# - "tfidf"       : similarité basée sur la composition textuelle (TF-IDF + cosine)
# - "categorie"   : similarité basée uniquement sur la même catégorie
#
# MODES "PLUS SAIN" GÉNÉRÉS :
# - "score_global"    : meilleur score santé OMS
# - "moins_sucre"     : moins de sucre
# - "moins_sel"       : moins de sel
# - "moins_saturees"  : moins de graisses saturées
# - "multi_criteres"  : logique complète OMS + NutriScore + NOVA
# =========================================================
SIMILARITY_MODES = ["ingredients", "tfidf", "categorie"]
HEALTHIER_MODES = [
    "score_global",
    "moins_sucre",
    "moins_sel",
    "moins_saturees",
    "multi_criteres"
]

# ==============================
# 1. Charger produits
# ==============================

QUERY = """
SELECT
    p.code_produit,
    p.nom_produit,
    p.categorie_principale,
    p.nutrition_grade,
    p.nova_group,
    v.sugars_100g,
    v.salt_100g,
    v.saturated_fat_100g,
    v.fiber_100g,
    v.proteins_100g,
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
    p.nova_group,
    v.sugars_100g,
    v.salt_100g,
    v.saturated_fat_100g,
    v.fiber_100g,
    v.proteins_100g
"""

# ==============================
# 2. Fonctions utilitaires
# ==============================

def nutriscore_value(grade):
    mapping = {
        "A": 5,
        "B": 4,
        "C": 3,
        "D": 2,
        "E": 1
    }
    return mapping.get(str(grade).upper(), 0)


def category_bonus(cat_a, cat_b):
    if not cat_a or not cat_b:
        return 0.0

    if str(cat_a).strip().lower() == str(cat_b).strip().lower():
        return 0.1

    return 0.0


def quality_bonus(source_grade, target_grade, source_nova, target_nova):
    bonus = 0.0

    source_grade_value = nutriscore_value(source_grade)
    target_grade_value = nutriscore_value(target_grade)

    # Bonus / malus sur NutriScore
    if target_grade_value > source_grade_value:
        bonus += 0.10
    elif target_grade_value == source_grade_value:
        bonus += 0.03
    elif target_grade_value < source_grade_value:
        bonus -= 0.10

    # Bonus / malus sur NOVA
    try:
        if source_nova is not None and target_nova is not None:
            source_nova = int(source_nova)
            target_nova = int(target_nova)

            if target_nova < source_nova:
                bonus += 0.05
            elif target_nova > source_nova:
                bonus -= 0.02
    except Exception:
        pass

    return bonus


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

    # Repères utilisés dans le scoring
    # (adaptés pour évaluer un produit à partir de ses valeurs /100g)
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

    # Bornage final
    score = max(0, min(100, score))

    return round(score, 4)


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

    # 1. Le produit cible ne doit pas être pire en NutriScore
    if target_nutri < source_nutri:
        return False

    # 2. Le produit cible ne doit pas être pire en NOVA
    try:
        if source_nova is not None and target_nova is not None:
            if int(target_nova) > int(source_nova):
                return False
    except Exception:
        pass

    # 3. Le score santé global doit être strictement meilleur
    if target_health_score <= source_health_score:
        return False

    # 4. Garde-fous critiques :
    # on refuse "plus sain" si le produit cible est nettement pire
    # sur des critères critiques
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

    # 5. Compter les améliorations nettes
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

    # 6. Détection des cas de compromis / trade-off :
    # si le produit cible améliore certains critères
    # mais le produit source reste meilleur sur d'autres critères majeurs,
    # on évite de dire trop vite "plus sain"
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

    # Si chaque produit a plusieurs avantages majeurs,
    # on considère que c'est un compromis nutritionnel,
    # donc pas une vraie alternative "plus saine"
    if target_advantages >= 2 and source_advantages >= 2:
        return False

    # 7. Exiger au moins 2 améliorations nettes
    if improvements < 2:
        return False

    # 8. Le gain global doit aussi être significatif
    if (target_health_score - source_health_score) < 3:
        return False

    return True


def is_healthier_by_mode(a, b, mode):
    """
    Détermine si b est une alternative plus saine que a
    selon le mode choisi par l'utilisateur.
    """

    try:
        if mode == "score_global":
            return (
                pd.notna(a["health_score"]) and
                pd.notna(b["health_score"]) and
                float(b["health_score"]) > float(a["health_score"])
            )

        elif mode == "moins_sucre":
            return (
                pd.notna(a["sugars_100g"]) and
                pd.notna(b["sugars_100g"]) and
                float(b["sugars_100g"]) < float(a["sugars_100g"])
            )

        elif mode == "moins_sel":
            return (
                pd.notna(a["salt_100g"]) and
                pd.notna(b["salt_100g"]) and
                float(b["salt_100g"]) < float(a["salt_100g"])
            )

        elif mode == "moins_saturees":
            return (
                pd.notna(a["saturated_fat_100g"]) and
                pd.notna(b["saturated_fat_100g"]) and
                float(b["saturated_fat_100g"]) < float(a["saturated_fat_100g"])
            )

        elif mode == "multi_criteres":
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

    return False


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


def jaccard(a, b):
    a, b = set(a), set(b)
    if not (a | b):
        return 0
    return len(a & b) / len(a | b)


def compute_similarity_score(mode, cos, jac, same_category):
    """
    Calcule le score de similarité selon le mode choisi.
    """

    if mode == "ingredients":
        return jac

    if mode == "tfidf":
        return cos

    if mode == "categorie":
        return 1.0 if same_category else 0.0

    raise ValueError(f"Mode de similarité inconnu : {mode}")


def similarity_method_label(mode):
    if mode == "ingredients":
        return "ingredients_jaccard"
    if mode == "tfidf":
        return "composition_avancee_tfidf"
    if mode == "categorie":
        return "meme_categorie"
    return "mode_inconnu"


def healthier_mode_label(mode):
    mapping = {
        "score_global": "score_global",
        "moins_sucre": "moins_sucre",
        "moins_sel": "moins_sel",
        "moins_saturees": "moins_saturees",
        "multi_criteres": "multi_criteres",
    }
    return mapping.get(mode, "mode_sante_inconnu")


def generate_recommendations_for_mode(df, sim_matrix, similarity_mode, healthier_mode):
    similar_results = []
    healthier_results = []

    print("===================================================")
    print("Mode de similarité en cours :", similarity_mode)
    print("Mode plus sain :", healthier_mode)
    print("===================================================")

    for i, a in df.iterrows():
        for j, b in df.iterrows():
            if i == j:
                continue

            same_category = (
                str(a["categorie_principale"]).strip().lower() ==
                str(b["categorie_principale"]).strip().lower()
            )

            # Mode "categorie" : on ne garde que les produits de la même catégorie
            if similarity_mode == "categorie" and not same_category:
                continue

            cos = sim_matrix[i, j]
            jac = jaccard(a["ingredients_clean"], b["ingredients_clean"])

            health_score_a = compute_health_score(
                a["sugars_100g"],
                a["salt_100g"],
                a["saturated_fat_100g"],
                a["fiber_100g"],
                a["proteins_100g"],
                a["nova_group"],
                a["nutrition_grade"]
            )

            health_score_b = compute_health_score(
                b["sugars_100g"],
                b["salt_100g"],
                b["saturated_fat_100g"],
                b["fiber_100g"],
                b["proteins_100g"],
                b["nova_group"],
                b["nutrition_grade"]
            )

            a_data = {
                "code_produit": a["code_produit"],
                "nutrition_grade": a["nutrition_grade"],
                "nova_group": a["nova_group"],
                "sugars_100g": a["sugars_100g"],
                "salt_100g": a["salt_100g"],
                "saturated_fat_100g": a["saturated_fat_100g"],
                "fiber_100g": a["fiber_100g"],
                "proteins_100g": a["proteins_100g"],
                "health_score": health_score_a
            }

            b_data = {
                "code_produit": b["code_produit"],
                "nutrition_grade": b["nutrition_grade"],
                "nova_group": b["nova_group"],
                "sugars_100g": b["sugars_100g"],
                "salt_100g": b["salt_100g"],
                "saturated_fat_100g": b["saturated_fat_100g"],
                "fiber_100g": b["fiber_100g"],
                "proteins_100g": b["proteins_100g"],
                "health_score": health_score_b
            }

            score = compute_similarity_score(
                similarity_mode,
                cos,
                jac,
                same_category
            )

            commons = list(set(a["ingredients_clean"]) & set(b["ingredients_clean"]))
            commons_sorted = sorted(commons)

            # ------------------------------
            # Garde-fous selon le mode choisi
            # ------------------------------
            if similarity_mode == "ingredients":
                if len(commons_sorted) < 2:
                    continue
                if score < 0.20:
                    continue

            elif similarity_mode == "tfidf":
                if score < 0.20:
                    continue

            elif similarity_mode == "categorie":
                if not same_category:
                    continue

            # ------------------------------
            # Recommandations similaires
            # ------------------------------
            similar_results.append({
                "code_produit_source": a["code_produit"],
                "code_produit_cible": b["code_produit"],
                "score_similarite": round(float(score), 4),
                "nb_ingredients_communs": len(commons_sorted),
                "ingredients_communs": ", ".join(commons_sorted[:8]),
                "methode": similarity_method_label(similarity_mode),
                "mode_sante": healthier_mode_label(healthier_mode),
                "type_recommandation": "similaire",
                "health_score_source": health_score_a,
                "health_score_cible": health_score_b
            })

            # ------------------------------
            # Recommandations plus saines
            # ------------------------------
            is_better = is_healthier_by_mode(a_data, b_data, healthier_mode)

            if is_better:
                healthier_results.append({
                    "code_produit_source": a["code_produit"],
                    "code_produit_cible": b["code_produit"],
                    "score_similarite": round(float(score), 4),
                    "nb_ingredients_communs": len(commons_sorted),
                    "ingredients_communs": ", ".join(commons_sorted[:8]),
                    "methode": similarity_method_label(similarity_mode),
                    "mode_sante": healthier_mode_label(healthier_mode),
                    "type_recommandation": "plus_saine",
                    "health_score_source": health_score_a,
                    "health_score_cible": health_score_b
                })

    similar_df = pd.DataFrame(similar_results)
    healthier_df = pd.DataFrame(healthier_results)

    print(f"[{similarity_mode} | {healthier_mode}] Total recommandations similaires :", len(similar_df))
    print(f"[{similarity_mode} | {healthier_mode}] Total recommandations plus saines :", len(healthier_df))

    # Top 5 pour chaque produit source et chaque type
    if not similar_df.empty:
        similar_df = similar_df.sort_values(
            ["code_produit_source", "score_similarite"],
            ascending=[True, False]
        )
        similar_df = similar_df.groupby("code_produit_source").head(5).reset_index(drop=True)

    if not healthier_df.empty:
        healthier_df = healthier_df.sort_values(
            ["code_produit_source", "score_similarite"],
            ascending=[True, False]
        )
        healthier_df = healthier_df.groupby("code_produit_source").head(5).reset_index(drop=True)

    print(f"[{similarity_mode} | {healthier_mode}] Top similaires gardés :", len(similar_df))
    print(f"[{similarity_mode} | {healthier_mode}] Top plus saines gardés :", len(healthier_df))

    return similar_df, healthier_df


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

    # Supprimer produits sans ingrédients
    df = df[df["ingredients_clean"].apply(len) > 0].reset_index(drop=True)

    print("Produits utilisés :", len(df))
    print("Modes de similarité à générer :", SIMILARITY_MODES)
    print("Modes plus sains à générer :", HEALTHIER_MODES)

    # ==============================
    # 5. Vectorisation TF-IDF
    # ==============================

    df["doc"] = df["ingredients_clean"].apply(lambda x: " ".join(x))

    vectorizer = TfidfVectorizer()
    X = vectorizer.fit_transform(df["doc"])

    sim_matrix = cosine_similarity(X)

    # ==============================
    # 6. Calcul des recommandations
    # ==============================

    all_results = []

    for similarity_mode in SIMILARITY_MODES:
        for healthier_mode in HEALTHIER_MODES:
            similar_df, healthier_df = generate_recommendations_for_mode(
                df=df,
                sim_matrix=sim_matrix,
                similarity_mode=similarity_mode,
                healthier_mode=healthier_mode
            )

            mode_result_df = pd.concat([similar_df, healthier_df], ignore_index=True)

            if not mode_result_df.empty:
                all_results.append(mode_result_df)

    if all_results:
        result_df = pd.concat(all_results, ignore_index=True)
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

    print("Total final inséré :", len(result_df))

    # ==============================
    # 7. Insertion en base
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

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM produit_similaire"))
        if not result_df.empty:
            result_df.to_sql("produit_similaire", conn, if_exists="append", index=False)

    print("✅ Recommandations similaires et plus saines enregistrées en base")
    print("✅ Modes générés :", ", ".join([similarity_method_label(m) for m in SIMILARITY_MODES]))
    print("✅ Modes santé générés :", ", ".join([healthier_mode_label(m) for m in HEALTHIER_MODES]))


if __name__ == "__main__":
    main()