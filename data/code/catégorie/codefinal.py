import pandas as pd
import ast
import re
import unicodedata

# =====================================================
# 1️⃣ CHARGEMENT INITIAL
# =====================================================

df = pd.read_csv("../../gold/nettoye.csv")

# =====================================================
# 2️⃣ CONFIGURATION GLOBALE
# =====================================================

mapping_fr = {
    'meals': 'plats prepares',
    'dietary supplements': 'complements alimentaires',
    'meal replacements': 'substituts de repas',
    'plant-based foods': 'aliments d origine vegetale',
    'beverages': 'boissons',
    'dairies': 'produits laitiers',
    'fermented foods': 'produits fermentes',
    'snacks': 'snacks',
    'fruit-based foods': 'aliments a base de fruits',
    'soy protein isolate': 'isolat de proteine de soja',
    'fructose': 'fructose',
    'soy lecithin': 'lecithine de soja',
    'sugar': 'sucre',
    'water': 'eau',
    'salt': 'sel',
    'milk': 'lait'
}

blacklist = [
    'peut contenir', 'traces de', 'manufactured in',
    'keep refrigerated', 'biologique', 'organic',
    'natural', 'naturel', 'non alimentaire',
    'unknown', 'en:fr', 'added for freshness',
    'non homogeneise', 'active cultures'
]

corrections = {
    "microcristalline cellulose": "microcrystalline cellulose",
    "cyanocobalamine": "cyanocobalamin",
    "calcium d-pantotherate": "calcium d-pantothenate",
    "xanthan caraghennes gum": "xanthan gum",
    "potassium iodure": "potassium iodide",
    "d-biotine r": "biotin"
}

functional_words = [
    "emulsifier", "thickener", "charge agent",
    "stabilizer", "flavouring", "flavoring"
]

standardization = {
    "cane sugar": "sucre",
    "brown sugar": "sucre",
    "white sugar": "sucre",
    "soy lecithin": "lecithine",
    "sunflower lecithin": "lecithine"
}

# =====================================================
# 3️⃣ FONCTIONS UTILITAIRES
# =====================================================

def remove_accents(text):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(c)
    )

def safe_literal_eval(val):
    if pd.isna(val):
        return None
    try:
        return ast.literal_eval(val)
    except:
        return None

def clean_text(text):
    text = str(text).lower()
    text = text.replace('*', '')
    text = re.sub(r'[()\[\]]', '', text)
    text = text.strip().strip('"').strip("'").strip('.')
    text = re.sub(r'\s+', ' ', text)
    text = remove_accents(text)
    return text

# =====================================================
# 4️⃣ NETTOYAGE COMPLET COLONNES
# =====================================================

def clean_full_pipeline(text):

    data = safe_literal_eval(text)
    if not data:
        return None

    cleaned = []

    for item in data:
        s = clean_text(item)

        # Blacklist
        if any(bad in s for bad in blacklist):
            continue

        # Supprimer pourcentages
        s = re.sub(r"\d+(\.\d+)?\s*%", "", s)

        # Supprimer mots fonctionnels
        for word in functional_words:
            s = s.replace(word, "")

        s = s.strip()

        # Corrections fautes
        if s in corrections:
            s = corrections[s]

        # Standardisation
        if s in standardization:
            s = standardization[s]

        # Traduction EN → FR
        if s in mapping_fr:
            s = mapping_fr[s]

        if s and len(s) > 1:
            cleaned.append(s)

    # Supprimer doublons internes en gardant ordre
    cleaned = list(dict.fromkeys(cleaned))

    return cleaned if cleaned else None

# =====================================================
# 5️⃣ APPLICATION SUR COLONNES ORIGINALES
# =====================================================

df["ingredients_text"] = df["ingredients_text"].apply(clean_full_pipeline)
df["categories"] = df["categories"].apply(clean_full_pipeline)

# Supprimer lignes sans ingrédients
df = df.dropna(subset=["ingredients_text"])

# =====================================================
# 6️⃣ SUPPRESSION PREMIER ELEMENT CATEGORIES
# =====================================================

def remove_first_category(categories):
    if categories and len(categories) > 0:
        return categories[1:]
    return categories

df["categories"] = df["categories"].apply(remove_first_category)

# =====================================================
# 7️⃣ EXPORT FINAL
# =====================================================

df.to_csv("../../gold/nettoye.csv", index=False)

print("✅ Pipeline complet exécuté avec succès.")
