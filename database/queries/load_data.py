import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

# ==============================
# CONFIGURATION / DEFAULTS
# ==============================

DEFAULT_DATABASE_URL = "postgresql://postgres:admin@localhost:5432/openfoodfacts_canada"
DEFAULT_CSV_FILE = "openfoodfacts_clean.csv"

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
            # MARQUE
            # -----------------------
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
                "url": safe(row.get("product_url")),
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
            conn.execute(text("""
                INSERT INTO valeurs_nutritionnelles (
                    code_produit,
                    saturated_fat_100g,
                    sugars_100g,
                    fiber_100g,
                    proteins_100g,
                    salt_100g,
                    carbohydrates_100g,
                    fat_100g
                )
                VALUES (
                    :code, :sat, :sug, :fib, :prot, :salt, :carb, :fat
                )
                ON CONFLICT DO NOTHING
            """), {
                "code": format_code(row.get("code")),
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

            def insert_many_to_many(field, table, column, link_table, id_column):
                if pd.isna(row.get(field)):
                    return

                values = str(row[field]).split(",")

                for v in values:
                    v = v.strip()
                    if not v:
                        continue

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

                    conn.execute(text(f"""
                        INSERT INTO {link_table}
                        VALUES (:code, :id)
                        ON CONFLICT DO NOTHING
                    """), {
                        "code": row["code"],
                        "id": entity_id
                    })

            insert_many_to_many("categories", "categorie", "categorie",
                                "produit_categorie", "id_categorie")

            insert_many_to_many("ingredients", "ingredient", "ingredients_nom",
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
