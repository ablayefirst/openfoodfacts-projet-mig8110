import csv

csv.field_size_limit(2**31 - 1)

file_in = "../../dataset/brut/nettoyage/netoyer.csv"
file_out = "../../dataset/brut/nettoyage/netoyer1.csv"

COLUMNS_TO_KEEP = [
    "code",
    "product_name",
    "generic_name",
    "brands", 
    "brands_en",
    "categories", 
    "categories_en",
    "food_groups_en",
    "labels", 
    "labels_en", 
    "countries_en",
    "manufacturing_places", 
    "origins", 
    "origins_en",
    "quantity",
    "url",
    "ingredients_text", 
    "allergens",
    "allergens_en",
    "traces", 
    "traces_en",
    "nutriscore_grade",
    "nutriscore_score",
    "energy-kcal_100g",
    "energy-kj_100g", 
    "energy_100g",
    "fat_100g",
    "saturated-fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
    "additives_n",
    "additives",
    "additives_en",
    "nova_group",
    "image_url",
    "image_small_url",
    "image_ingredients_url",
    "image_ingredients_small_url",
    "image_nutrition_url"
]

with open(file_in, "r", encoding="utf-8", newline="") as f_in, \
     open(file_out, "w", encoding="utf-8", newline="") as f_out:

    reader = csv.reader(f_in, delimiter=",")  # CORRECTION
    writer = csv.writer(
        f_out,
        delimiter=",",
        quoting=csv.QUOTE_ALL,
        escapechar="\\"
    )

    header = next(reader)

    indices = []
    for col in COLUMNS_TO_KEEP:
        if col in header:
            indices.append(header.index(col))
        else:
            print(f"Colonne absente dans le fichier : {col}")

    writer.writerow([header[i] for i in indices])

    for row in reader:
        if len(row) != len(header):
            continue
        writer.writerow([row[i] for i in indices])

print("Fichier généré :", file_out)
