import os

import pandas as pd
from sqlalchemy import create_engine, text


def get_database_url() -> str:
    driver = os.getenv("POSTGRES_SQLALCHEMY_DRIVER", "postgresql+psycopg2")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "openfood_db")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres123")
    return f"{driver}://{user}:{password}@{host}:{port}/{db}"


# ==============================
# 1. Charger produits
# ==============================
# CORRECTIONS :
#   - Suppression du JOIN vers valeurs_nutritionnelles (n'existe pas dans le schéma)
#   - Suppression du JOIN vers produit_ingredient / ingredient (n'existent pas)
#   - nom_produit → nom  (nom réel de la colonne dans la table produit)
#   - proteins_100g supprimé (colonne absente de la table produit)
#   - Les ingrédients sont récupérés depuis produit_ingredient_similaire + ingredient_similaire
#     en suivant la logique du chargement (ordre ASC pour respecter la séquence)

QUERY = """
SELECT
    p.code_barre AS code_produit,
    p.nom_produit AS nom,
    p.categorie_principale,
    p.nutrition_grade,
    p.nova_group,
    p.sugars_100g,
    p.salt_100g,
    p.saturated_fat_100g,
    p.fiber_100g,
    p.carbohydrates_100g AS carbs_100g,

    COALESCE(
        string_agg(DISTINCT i.nom_canonique, ', '),
        ''
    )
    ||
    CASE 
        WHEN COUNT(s.nom_synonyme) > 0 
             AND COUNT(i.nom_canonique) > 0
        THEN ', '
        ELSE ''
    END
    ||
    COALESCE(
        string_agg(DISTINCT s.nom_synonyme, ', '),
        ''
    ) AS ingredients_text

FROM produit p

LEFT JOIN contient c
    ON p.id_produit = c.id_produit

LEFT JOIN ingredient_standardise i
    ON c.id_ingredient = i.id_ingredient

LEFT JOIN ingredient_synonyme s
    ON i.id_ingredient = s.id_ingredient

GROUP BY
    p.code_barre,
    p.nom_produit,
    p.categorie_principale,
    p.nutrition_grade,
    p.nova_group,
    p.sugars_100g,
    p.salt_100g,
    p.saturated_fat_100g,
    p.fiber_100g,
    p.carbohydrates_100g;
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


def compute_health_score(sugar, salt, fat_sat, fiber, nova, nutriscore):
    """
    Score santé inspiré des recommandations OMS.

    - Pénalise fortement le sucre, le sel et les graisses saturées
    - Récompense les fibres
    - Intègre NOVA et NutriScore comme facteurs complémentaires

    CORRECTION : paramètre proteins supprimé (colonne absente du schéma)

    Le score final est borné entre 0 et 100.
    Plus le score est élevé, plus le produit est considéré comme sain.
    """

    score = 100.0

    WHO_SUGAR_IDEAL = 25.0
    WHO_SUGAR_MAX   = 50.0
    WHO_SALT_MAX    = 5.0
    WHO_SAT_FAT_MAX = 22.0
    WHO_FIBER_MIN   = 25.0

    # ----------------------------
    # 1. Pénalité sucre
    # ----------------------------
    try:
        if sugar is not None and pd.notna(sugar):
            sugar = float(sugar)

            sugar_ratio_ideal = sugar / WHO_SUGAR_IDEAL
            sugar_ratio_max   = sugar / WHO_SUGAR_MAX

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
    # 5. Ajustement NOVA
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
    # 6. Ajustement NutriScore
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
):
    # CORRECTION : paramètres proteins supprimés (colonne absente du schéma)

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

    # 4. Garde-fous critiques
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

    if target_nutri > source_nutri:
        improvements += 1

    # 6. Détection des cas de compromis / trade-off
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

    if target_advantages >= 2 and source_advantages >= 2:
        return False

    # 7. Exiger au moins 2 améliorations nettes
    if improvements < 2:
        return False

    # 8. Le gain global doit aussi être significatif
    if (target_health_score - source_health_score) < 3:
        return False

    return True


def clean(text):
    if not text:
        return []

    text = str(text).lower()
    text = text.replace("(", ",").replace(")", ",")
    text = text.replace("|", ",")  # 🔥 important pour synonymes

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


def ensure_similarity_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS produit_similaire (
                code_produit_source TEXT REFERENCES produit(code_barre) ON DELETE CASCADE,
                code_produit_cible  TEXT REFERENCES produit(code_barre) ON DELETE CASCADE,
                type_recommandation TEXT NOT NULL,
                score_similarite    NUMERIC,
                nb_ingredients_communs INTEGER,
                ingredients_communs TEXT,
                methode             TEXT,
                health_score_source NUMERIC,
                health_score_cible  NUMERIC,
                PRIMARY KEY (code_produit_source, code_produit_cible, type_recommandation)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_produit_similaire_source_type
            ON produit_similaire(code_produit_source, type_recommandation)
            """
        )
    )


# ==============================
# 3. Main
# ==============================

def build_similarity_recommendations(**_):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    database_url = get_database_url()
    print(
        "DATABASE_URL utilisée = "
        f"{os.getenv('POSTGRES_SQLALCHEMY_DRIVER', 'postgresql+psycopg2')}://"
        f"{os.getenv('POSTGRES_USER', 'postgres')}:***@"
        f"{os.getenv('POSTGRES_HOST', 'postgres')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'openfood_db')}"
    )
    engine = create_engine(database_url)

    df = pd.read_sql(QUERY, engine)

    # ==============================
    # 4. Nettoyage des ingrédients
    # ==============================

    df["ingredients_clean"] = df["ingredients_text"].apply(clean)

    # Supprimer produits sans ingrédients
    df = df[df["ingredients_clean"].apply(len) > 0].reset_index(drop=True)

    print("Produits utilisés :", len(df))

    with engine.begin() as conn:
        ensure_similarity_table(conn)

    if len(df) < 2:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM produit_similaire"))
        print("Pas assez de produits avec ingrédients pour générer des recommandations.")
        return {"rows_products": int(len(df)), "rows_recommendations": 0}

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

    similar_results  = []
    healthier_results = []

    for i, a in df.iterrows():
        for j, b in df.iterrows():
            if i == j:
                continue

            # Comparer seulement dans la même catégorie
            if a["categorie_principale"] != b["categorie_principale"]:
                continue

            cos = sim_matrix[i, j]
            jac = jaccard(a["ingredients_clean"], b["ingredients_clean"])

            cat_bonus = category_bonus(
                a["categorie_principale"],
                b["categorie_principale"]
            )

            qual_bonus = quality_bonus(
                a["nutrition_grade"],
                b["nutrition_grade"],
                a["nova_group"],
                b["nova_group"]
            )

            # CORRECTION : proteins_100g supprimé de compute_health_score
            health_score_a = compute_health_score(
                a["sugars_100g"],
                a["salt_100g"],
                a["saturated_fat_100g"],
                a["fiber_100g"],
                a["nova_group"],
                a["nutrition_grade"]
            )

            health_score_b = compute_health_score(
                b["sugars_100g"],
                b["salt_100g"],
                b["saturated_fat_100g"],
                b["fiber_100g"],
                b["nova_group"],
                b["nutrition_grade"]
            )

            health_diff = health_score_b - health_score_a

            score = 0.55 * cos + 0.20 * jac + cat_bonus + qual_bonus + (0.05 * health_diff)

            commons        = list(set(a["ingredients_clean"]) & set(b["ingredients_clean"]))
            commons_sorted = sorted(commons)

            # Garde-fous qualité
            if len(commons_sorted) == 0:
                continue

            if len(commons_sorted) < 2:
                continue

            if score < 0.20:
                continue

            # ------------------------------
            # Recommandations similaires
            # ------------------------------
            similar_results.append({
                "code_produit_source":   a["code_produit"],
                "code_produit_cible":    b["code_produit"],
                "score_similarite":      round(float(score), 4),
                "nb_ingredients_communs": len(commons_sorted),
                "ingredients_communs":   ", ".join(commons_sorted[:8]),
                "methode":               "tfidf_jaccard_qualite_healthscore_oms_ameliore",
                "type_recommandation":   "similaire",
                "health_score_source":   health_score_a,
                "health_score_cible":    health_score_b,
            })

            # ------------------------------
            # Recommandations plus saines
            # CORRECTION : proteins supprimés des paramètres de is_healthier
            # ------------------------------
            if is_healthier(
                a["nutrition_grade"],
                b["nutrition_grade"],
                a["nova_group"],
                b["nova_group"],
                health_score_a,
                health_score_b,
                a["sugars_100g"],
                b["sugars_100g"],
                a["salt_100g"],
                b["salt_100g"],
                a["saturated_fat_100g"],
                b["saturated_fat_100g"],
                a["fiber_100g"],
                b["fiber_100g"],
            ):
                healthier_results.append({
                    "code_produit_source":   a["code_produit"],
                    "code_produit_cible":    b["code_produit"],
                    "score_similarite":      round(float(score), 4),
                    "nb_ingredients_communs": len(commons_sorted),
                    "ingredients_communs":   ", ".join(commons_sorted[:8]),
                    "methode":               "tfidf_jaccard_qualite_healthscore_oms_ameliore",
                    "type_recommandation":   "plus_saine",
                    "health_score_source":   health_score_a,
                    "health_score_cible":    health_score_b,
                })

    # ==============================
    # 7. Création des DataFrames
    # ==============================

    similar_df  = pd.DataFrame(similar_results)
    healthier_df = pd.DataFrame(healthier_results)

    print("Total recommandations similaires :", len(similar_df))
    print("Total recommandations plus saines :", len(healthier_df))

    # ==============================
    # 8. Garder top 5 pour chaque type
    # ==============================

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

    print("Top similaires gardés :", len(similar_df))
    print("Top plus saines gardés :", len(healthier_df))

    # ==============================
    # 9. Fusion finale
    # ==============================

    result_df = pd.concat([similar_df, healthier_df], ignore_index=True)

    print("Total final inséré :", len(result_df))

    # ==============================
    # 10. Insertion en base
    # ==============================

    with engine.begin() as conn:
        ensure_similarity_table(conn)
        conn.execute(text("DELETE FROM produit_similaire"))
        if not result_df.empty:
            print("Colonnes result_df :", result_df.columns.tolist())
            print(result_df[[
                "code_produit_source",
                "code_produit_cible",
                "type_recommandation",
                "health_score_source",
                "health_score_cible"
            ]].head(10))
            result_df.to_sql("produit_similaire", conn, if_exists="append", index=False)

    print("✅ Recommandations similaires et plus saines enregistrées en base")
    return {"rows_products": int(len(df)), "rows_recommendations": int(len(result_df))}


def main():
    build_similarity_recommendations()


if __name__ == "__main__":
    main()