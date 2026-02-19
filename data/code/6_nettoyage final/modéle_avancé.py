import pandas as pd
import ast


# =====================================================
# 1. VALEURS UNKNOWN A IGNORER
# =====================================================

UNKNOWN_VALUES = {"unknown", "unknow", "none", "", "null", "nan"}


# =====================================================
# 2. NORMALISATION ALLERGENES (ANGLAIS → CANONIQUE)
# =====================================================

ALLERGEN_CANONICAL = {

    "milk": "lait",                     "milk(IA)": "lait","milk(ia)": "lait",
    "lait": "lait",                     "lait(IA)": "lait","lait(ia)": "lait",

    "egg": "oeufs",                     "egg(ia)": "oeufs","egg(IA)": "oeufs",
    "eggs": "oeufs",                    "eggs(IA)": "oeufs","eggs(ia)": "oeufs",
    "oeuf": "oeufs",                    "oeuf(IA)": "oeufs","oeuf(ia)": "oeufs",
    "oeufs": "oeufs",                   "oeufs(ia)": "oeufs","oeufs(IA)": "oeufs",
    

    "wheat": "ble",                     "wheat(IA)": "ble","wheat(ia)": "ble",
    "blé": "ble",                       "blé(ia)": "ble","blé(IA)": "ble",
    "ble": "ble",                       "ble(ia)": "ble","ble(IA)": "ble",
    "flour": "ble",                     "flour(IA)": "ble","flour(ia)": "ble",
    "farine": "ble",                    "farine(IA)": "ble","farine(ia)": "ble",
    "gluten": "ble",                    "gluten(IA)": "ble","gluten(ia)": "ble",
    "glutens": "ble",                   "glutens(IA)": "ble","glutens(ia)": "ble",

    "soy": "soja",                      "soy(IA)": "soja","soy(ia)": "soja",
    "soya": "soja",                     "soya(IA)": "soja","soya(ia)": "soja",
    "soja": "soja",                     "soja(IA)": "soja","soja(ia)": "soja",
    "soybeans" : "soja",                "soybeans(IA)" : "soja","soybeans(ia)" : "soja",
    "soybean" : "soja",                 "soybean(IA)" : "soja","soybean(ia)" : "soja",

    "sesame": "sesame",                 "sesame(IA)": "sesame","sesame(ia)": "sesame",
    "sésame": "sesame",                 "sésame(IA)": "sesame","sésame(ia)": "sesame",

    "mustard": "moutarde",              "mustard(IA)": "moutarde","mustard(ia)": "moutarde",
    "moutarde": "moutarde",             "moutarde(IA)": "moutarde","moutarde(ia)": "moutarde",

    "peanut": "arachides",              "peanut(IA)": "arachides","peanut(ia)": "arachides",
    "peanuts": "arachides",             "peanuts(IA)": "arachides","peanuts(ia)": "arachides",
    "arachide": "arachides",            "arachide(IA)": "arachides","arachide(ia)": "arachides",
    "arachides": "arachides",           "arachides(IA)": "arachides","arachides(ia)": "arachides",

    "fish": "poisson",                  "fish(IA)": "poisson","fish(ia)": "poisson",
    "poisson": "poisson",               "poisson(IA)": "poisson","poisson(ia)": "poisson",

    "shrimp": "fruits_de_mer",          "shrimp(IA)": "fruits_de_mer","shrimp(ia)": "fruits_de_mer",
    "crab": "fruits_de_mer",            "crab(IA)": "fruits_de_mer","crab(ia)": "fruits_de_mer",
    "lobster": "fruits_de_mer",         "lobster(IA)": "fruits_de_mer","lobster(ia)": "fruits_de_mer",
    "crevette": "fruits_de_mer",        "crevette(IA)": "fruits_de_mer","crevette(ia)": "fruits_de_mer",
    "crabe": "fruits_de_mer",           "crabe(IA)": "fruits_de_mer","crabe(ia)": "fruits_de_mer",
    "homard": "fruits_de_mer",          "homard(IA)": "fruits_de_mer","homard(ia)": "fruits_de_mer",

    "almond": "noix",       "almond(IA)": "noix","almond(ia)": "noix",
    "walnut": "noix",       "walnut(IA)": "noix","walnut(ia)": "noix",
    "cashew": "noix",       "cashew(IA)": "noix","cashew(ia)": "noix",
    "hazelnut": "noix",     "hazelnut(IA)": "noix","hazelnut(ia)": "noix",
    "amande": "noix",       "amande(IA)": "noix","amande(ia)": "noix",
    "noix": "noix",         "noix(IA)": "noix", "noix(ia)": "noix",
    "cajou": "noix",        "cajou(IA)": "noix","cajou(ia)": "noix",
    "noisette": "noix"      ,"noisette(IA)": "noix","noisette(ia)": "noix"
}


# =====================================================
# 3. MOTS-CLES POUR DETECTION
# =====================================================

ALLERGEN_DICT = {

    "lait": ["lait", "milk", "whey", "casein"],

    "oeufs": ["oeuf", "oeufs", "egg", "eggs"],

    "gluten": ["blé", "ble", "wheat", "farine", "flour", "gluten"],

    "soja": ["soja", "soy", "soya"],

    "sesame": ["sésame", "sesame"],

    "moutarde": ["moutarde", "mustard"],

    "arachides": ["arachide", "arachides", "peanut", "peanuts"],

    "poisson": ["poisson", "fish"],

    "fruits_de_mer": [
        "crevette", "shrimp",
        "crabe", "crab",
        "homard", "lobster"
    ],

    "noix": [
        "amande", "almond",
        "noix", "walnut",
        "cajou", "cashew",
        "noisette", "hazelnut"
    ]
}


# =====================================================
# 4. NORMALISER NOM ALLERGENE
# =====================================================

def normalize_allergen(allergen):

    clean = allergen.replace("(IA)", "").strip().lower()

    return ALLERGEN_CANONICAL.get(clean, clean)


# =====================================================
# 5. SPLIT INGREDIENTS
# =====================================================

def split_ingredients(text):

    if isinstance(text, str):

        text = text.lower().replace(";", ",")

        return [i.strip() for i in text.split(",")]

    return []


# =====================================================
# 6. CONVERTIR COLONNE ALLERGENS EN LISTE PROPRE
# =====================================================

def convert_allergens_to_list(allergens):

    if pd.isna(allergens):
        return []

    if isinstance(allergens, str):

        if allergens.strip().lower() in UNKNOWN_VALUES:
            return []

        try:

            parsed = ast.literal_eval(allergens)

            if isinstance(parsed, list):

                return [
                    a for a in parsed
                    if a.strip().lower() not in UNKNOWN_VALUES
                ]

            return [parsed]

        except:
            return []

    if isinstance(allergens, list):

        return [
            a for a in allergens
            if a.strip().lower() not in UNKNOWN_VALUES
        ]

    return []


# =====================================================
# 7. DETECTER ALLERGENES ET AJOUTER (IA)
# =====================================================

def detect_allergens(ingredients_list, existing_allergens):

    detected = set()

    existing_normalized = {
        normalize_allergen(a)
        for a in existing_allergens
    }

    for ingredient in ingredients_list:

        ingredient = ingredient.lower()

        for allergen, keywords in ALLERGEN_DICT.items():

            if any(keyword in ingredient for keyword in keywords):

                canonical = normalize_allergen(allergen)

                if canonical not in existing_normalized:

                    detected.add(f"{canonical}(IA)")

    return detected


# =====================================================
# 8. METTRE A JOUR CHAQUE LIGNE
# =====================================================

def update_allergens(row):

    ingredients_list = split_ingredients(row["ingredients_text"])

    existing_allergens = convert_allergens_to_list(row["allergens"])

    new_allergens = detect_allergens(
        ingredients_list,
        existing_allergens
    )

    updated = existing_allergens + list(new_allergens)

    if not updated:
        return "unknown"

    return updated


# =====================================================
# 9. PROCESS DATASET
# =====================================================

def process_dataset(input_file, output_file):

    df = pd.read_csv(input_file)

    df["allergens"] = df.apply(update_allergens, axis=1)

    df.to_csv(output_file, index=False)

    print("Traitement terminé.")
    print("Fichier sauvegardé :", output_file)


# =====================================================
# 10. EXECUTION
# =====================================================

if __name__ == "__main__":

    input_file = "../../gold/nettoye.csv"

    output_file = "../../gold/nettoye.csv"

    process_dataset(input_file, output_file)
