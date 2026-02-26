import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

# --------------------------------------------------------------------
# Script de chargement CSV → base de données
# - Ce fichier lit un CSV nettoyé d'OpenFoodFacts et insère les données
#   dans la base PostgreSQL définie par `DEFAULT_DATABASE_URL` ou
#   passée via `--db-url`.
# - Mapping important (CSV colonne → colonne BDD):
#     - `code`/`code_produit`  : identifiant produit (clé primaire)
#     - `product_name` → `nom_produit`
#     - `brands` → table `marque.brands` (unique)
#     - `categories` → table `categorie.categorie` (séparées par `,`)
#     - `ingredients_text` → table `ingredient.ingredients_nom` (séparées par `,`)
#     - `labels`, `countries_en`, `allergens` → tables de lookup respectives
#     - diverses colonnes nutritionnelles → `valeurs_nutritionnelles`
# - Protection contre la duplication:
#     - Tables lookup (ingredient, label, etc.) ont une colonne `UNIQUE`.
#       Le code vérifie l'existence puis insère si nécessaire.
#     - `produit` et `valeurs_nutritionnelles` sont insérés avec
#       `ON CONFLICT DO NOTHING` : si la `code_produit` existe déjà, on
#       n'écrase pas la ligne existante (pas d'update automatique).
# - Remarques:
#     - Le script ne met pas à jour les enregistrements existants :
#       il ignore la ligne si la clé existe. Si vous voulez mettre à jour
#       les champs existants, il faudra remplacer `ON CONFLICT DO NOTHING`
#       par un `ON CONFLICT (...) DO UPDATE SET ...` approprié.
#     - `format_code()` s'assure que les codes issus du CSV (ex: 264.0)
#       deviennent des chaînes sans décimales; la BDD attend un TEXT.
# --------------------------------------------------------------------

# ==============================
# CONFIGURATION / DEFAULTS
# ==============================

DEFAULT_DATABASE_URL = "postgresql://postgres:admin@localhost:5432/openfoodfacts_canada"
DEFAULT_CSV_FILE = "dataset_nettoyer.csv"

# ==============================
# FONCTION UTILITAIREpython database/queries/load_data.py --source data/silver/openfoodfacts_clean.csv
# ==============================

def get_or_create(conn, table, column, value):
    if not value or pd.isna(value):
        return None

    value = value.strip()

    result = conn.execute(
        text(f"SELECT id_{table} FROM {table} WHERE {column} = :val"),
        {"val": value}
    ).fetchone()

    if result:
        return result[0]

    result = conn.execute(
        text(f"""
            INSERT INTO {table} ({column})
            VALUES (:val)
            RETURNING id_{table}
        """),
        {"val": value}
    )

    return result.scalar()


# --------------------------------------------------
# Analyse et insertion principale
# - `main()` lit le CSV, puis pour chaque ligne:
#   1) récupère/crée la marque (`marque`) via une requête SELECT/INSERT
#   2) insère la ligne produit dans `produit` (avec `ON CONFLICT DO NOTHING`)
#   3) insère les valeurs nutritionnelles dans `valeurs_nutritionnelles`
#   4) éclate les champs listés (categories, ingredients_text, etc.)
#      et gère les tables N-N (`produit_*`) en évitant les doublons
#      (via SELECT préalable et `ON CONFLICT DO NOTHING` sur les liens)
# - `safe()` normalise les valeurs pandas NA → None pour SQLAlchemy.
# - `format_code()` nettoie les identifiants produits mal typés (ex: 264.0)
#   pour produire une représentation stable utilisable comme clé.
# --------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser(description="Charger les produits OpenFoodFacts dans la BDD")
    p.add_argument("--source", help="Chemin vers le fichier CSV source", default=DEFAULT_CSV_FILE)
    p.add_argument("--db-url", help="URL de connexion à la base de données", default=DEFAULT_DATABASE_URL)
    p.add_argument("--dry-run", help="Lire le CSV sans écrire dans la base (contrôle)", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()

    csv_path = Path(args.source)
    if not csv_path.exists():
        print(f"Fichier source introuvable: {csv_path}. Vérifiez le chemin ou utilisez --source.")
        sys.exit(1)

    # Si dry-run, on évite toute connexion DB et on se contente de valider le CSV
    df = pd.read_csv(csv_path)

    if args.dry_run:
        print(f"DRY-RUN: fichier lu OK — {len(df)} lignes, {len(df.columns)} colonnes")
        print("Extrait (3 premières lignes):")
        print(df.head(3).to_string(index=False))
        return

    try:
        engine = create_engine(args.db_url)
    except UnicodeDecodeError as e:
        print("Erreur de décodage lors de la connexion DB : le DSN contient probablement des caractères non-UTF8.")
        print("Passez l'URL correcte via --db-url, par ex : postgresql://postgres:admin@localhost:5432/openfoodfacts_canada")
        sys.exit(1)
    except Exception as e:
        print("Erreur lors de la création de la connexion à la base de données:", e)
        print("Vérifiez l'URL passée avec --db-url ou la variable DEFAULT_DATABASE_URL dans le script.")
        sys.exit(1)

    for _, row in df.iterrows():
        with engine.begin() as conn:
            # -----------------------
            # -----------------------
            # MARQUE
            # -----------------------
            # On cherche d'abord la marque existante via `brands` (colonne
            # `brands` de la table `marque`). Si elle n'existe pas, on
            # l'insère et on récupère `id_marque`. La colonne `brands`
            # est définie UNIQUE dans le schéma SQL, donc on évite les
            # doublons au niveau BDD.
            marque_id = None
            if pd.notna(row.get("brands")):
                result = conn.execute(
                    text("SELECT id_marque FROM marque WHERE brands = :b"),
                    {"b": row["brands"]}
                ).fetchone()

                if result:
                    marque_id = result[0]
                else:
                    marque_id = conn.execute(
                        text("""
                            INSERT INTO marque (brands)
                            VALUES (:b)
                            RETURNING id_marque
                        """),
                        {"b": row["brands"]}
                    ).scalar()

            # -----------------------
            # HELPERS
            # -----------------------
            def safe(v):
                return None if pd.isna(v) else v

            def format_code(v):
                if pd.isna(v):
                    return None
                try:
                    # convert floats like 264.0 to '264'
                    if isinstance(v, float) and v.is_integer():
                        return str(int(v))
                    return str(v)
                except Exception:
                    return str(v)

            # -----------------------
            # PRODUIT
            # -----------------------
            # Insertion du produit principal. On mappe les colonnes du CSV
            # vers les colonnes BDD. IMPORTANT: l'option `ON CONFLICT DO NOTHING`
            # empêche la création d'un doublon si `code_produit` existe déjà.
            # Cela signifie aussi qu'on ne mettra pas à jour un produit déjà
            # présent; on l'ignore.
            conn.execute(text("""
                INSERT INTO produit (
                    code_produit,
                    nom_produit,
                    quantite,
                    nutrition_grade,
                    nutriscore_score,
                    nova_group,
                    url,
                    image_url,
                    image_small_url,
                    image_ingredients_url,
                    image_ingredients_small_url,
                    image_nutrition_url,
                    id_marque
                )
                VALUES (
                    :code, :nom, :quantite, :grade, :score, :nova,
                    :url, :img, :img_s, :img_i, :img_is, :img_n,
                    :marque
                )
                ON CONFLICT DO NOTHING
            """), {
                "code": format_code(row.get("code")),
                "nom": safe(row.get("product_name")),
                "quantite": safe(row.get("quantity")),
                "grade": safe(row.get("nutriscore_grade")),
                "score": safe(row.get("nutriscore_score")),
                "nova": safe(row.get("nova_group")),
                "url": safe(row.get("url")),
                "img": safe(row.get("image_url")),
                "img_s": safe(row.get("image_small_url")),
                "img_i": safe(row.get("image_ingredients_url")),
                "img_is": safe(row.get("image_ingredients_small_url")),
                "img_n": safe(row.get("image_nutrition_url")),
                "marque": marque_id
            })

            # -----------------------
            # VALEURS NUTRITIONNELLES
            # -----------------------
            # Les valeurs nutritionnelles sont liées 1-1 à `produit` via
            # `code_produit` (clé primaire dans `valeurs_nutritionnelles` et
            # référence vers `produit`). Ici aussi on utilise
            # `ON CONFLICT DO NOTHING` pour éviter les duplications.
            energy_kcal = safe(row.get("energy_kcal_100g"))
            if energy_kcal is None:
                energy_kcal = safe(row.get("energy-kcal_100g"))

            conn.execute(text("""
                INSERT INTO valeurs_nutritionnelles (
                    code_produit,
                    energy_kcal_100g,
                    saturated_fat_100g,
                    sugars_100g,
                    fiber_100g,
                    proteins_100g,
                    salt_100g,
                    carbohydrates_100g,
                    fat_100g
                )
                VALUES (
                    :code, :kcal, :sat, :sug, :fib, :prot, :salt, :carb, :fat
                )
                ON CONFLICT DO NOTHING
            """), {
                "code": format_code(row.get("code")),
                "kcal": energy_kcal,
                "sat": safe(row.get("saturated_fat_100g")),
                "sug": safe(row.get("sugars_100g")),
                "fib": safe(row.get("fiber_100g")),
                "prot": safe(row.get("proteins_100g")),
                "salt": safe(row.get("salt_100g")),
                "carb": safe(row.get("carbohydrates_100g")),
                "fat": safe(row.get("fat_100g"))
                })

            # -----------------------
            # LISTES (split)
            # -----------------------
            # Pour les champs multi-valeurs (séparés par des virgules), on
            # éclate la chaîne, on normalise chaque valeur, on vérifie si
            # l'entité existe dans la table de lookup (ex: `ingredient`),
            # sinon on l'insère, puis on crée la liaison N-N dans la table
            # d'association (`produit_ingredient`, etc.). Les tables de
            # lookup ont des contraintes UNIQUE sur leur colonne de nom,
            # évitant ainsi les duplications.

            def insert_many_to_many(field, table, column, link_table, id_column):
                # Si la colonne est vide/NA, rien à faire
                if pd.isna(row.get(field)):
                    return

                values = str(row[field]).split(",")

                for v in values:
                    v = v.strip()
                    if not v:
                        continue

                    # Vérifier si l'entité existe déjà
                    result = conn.execute(
                        text(f"SELECT {id_column} FROM {table} WHERE {column}=:v"),
                        {"v": v}
                    ).fetchone()

                    if result:
                        entity_id = result[0]
                    else:
                        entity_id = conn.execute(
                            text(f"""
                                INSERT INTO {table} ({column})
                                VALUES (:v)
                                RETURNING {id_column}
                            """),
                            {"v": v}
                        ).scalar()

                    # Insérer la relation N-N (produit <-> entité). Attention
                    # : on fournit le code produit formaté afin que la clé
                    # corresponde au type attendu par la table `produit`
                    # (TEXT). Si la contrainte PK existe déjà, `ON CONFLICT`
                    # évitera de créer un doublon.
                    conn.execute(text(f"""
                        INSERT INTO {link_table}
                        VALUES (:code, :id)
                        ON CONFLICT DO NOTHING
                    """), {
                        "code": format_code(row.get("code")),
                        "id": entity_id
                    })

            insert_many_to_many("categories", "categorie", "categorie",
                                "produit_categorie", "id_categorie")

            insert_many_to_many("ingredients_text", "ingredient", "ingredients_nom",
                                "produit_ingredient", "id_ingredient")

            insert_many_to_many("allergens", "allergene", "allergens",
                                "produit_allergene", "allergen_id")

            insert_many_to_many("labels", "label", "labels",
                                "produit_label", "label_id")

            insert_many_to_many("countries_en", "pays", "countries_en",
                                "produit_pays", "id_pays")

    print("Chargement terminé avec succès.")


if __name__ == "__main__":
    main()
