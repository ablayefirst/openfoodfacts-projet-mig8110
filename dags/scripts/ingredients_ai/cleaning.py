import re
import unicodedata


# =========================
# 🔤 REMOVE ACCENTS
# =========================
def remove_accents(text):
    if not text:
        return ""

    return ''.join(
        c for c in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(c)
    )


# =========================
# 🧹 CLEAN TEXT
# =========================
def clean_text(text):
    """
    Nettoyage global du texte ingrédients.

    - remove accents
    - lower
    - suppression caractères spéciaux
    - normalisation espaces
    """

    if not text or not isinstance(text, str):
        return ""

    # 🔥 1. remove accents
    text = remove_accents(text)

    # 🔥 2. lower
    text = text.lower()

    # 🔥 3. remplacer underscore
    text = text.replace("_", " ")

    # 🔥 4. garder lettres + chiffres + ponctuation utile
    text = re.sub(r"[^a-z0-9,() \-]", " ", text)

    # 🔥 5. normaliser espaces
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================
# ✏️ CORRECTIONS BASIQUES
# =========================
def basic_spell_fix(text):
    """
    Corrections simples (typos fréquentes)
    """

    if not text:
        return ""

    fixes = {
        "canthan": "xanthan",
        "protien": "protein",
        "lecitin": "lecithin",
        "suggar": "sugar",
        "milkk": "milk",
    }

    for wrong, correct in fixes.items():
        # 🔥 remplacement sécurisé (mot entier)
        text = re.sub(rf"\b{wrong}\b", correct, text)

    return text


# =========================
# 🚫 NOISE DETECTION
# =========================
def is_noise(text):
    """
    Détecte du bruit non alimentaire
    """

    if not text:
        return True

    text = text.lower()

    noise_words = {
        "www", "http", "barcode", "scan",
        "call", "distributed", "store",
        "product", "made", "facility"
    }

    return any(word in text for word in noise_words)


# =========================
# 🔪 SPLIT PARENTHESIS
# =========================
def split_sub_ingredients(text):
    """
    Ajoute des espaces autour des parenthèses
    pour aider le parsing
    """

    if not text:
        return ""

    return text.replace("(", " ( ").replace(")", " ) ")