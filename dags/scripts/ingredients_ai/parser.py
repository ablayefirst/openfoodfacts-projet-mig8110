# =========================
# 🔍 PARSE INGREDIENTS
# =========================
def parse_ingredients(text):
    """
    Parse une string d'ingrédients en respectant les parenthèses.

    Exemple:
    "milk powder (skimmed milk, sugar), cocoa butter"
    →
    [
        "milk powder (skimmed milk, sugar)",
        "cocoa butter"
    ]
    """

    # 🔹 sécurité input
    if not text or not isinstance(text, str):
        return []

    ingredients = []
    current = ""
    depth = 0  # niveau de parenthèse

    for char in text:

        # 🔹 entrée dans parenthèses
        if char == "(":
            depth += 1

        # 🔹 sortie de parenthèses (🔥 FIX CRITIQUE)
        elif char == ")":
            depth = max(depth - 1, 0)

        # 🔹 split UNIQUEMENT hors parenthèses
        if char == "," and depth == 0:
            ingredient = current.strip()
            if ingredient:
                ingredients.append(ingredient)
            current = ""
        else:
            current += char

    # 🔹 dernier élément
    last = current.strip()
    if last:
        ingredients.append(last)

    return ingredients


# =========================
# 🧪 NETTOYAGE POST-PARSE
# =========================
def clean_parsed_ingredients(ingredients):
    """
    Nettoyage après parsing :
    - supprime éléments vides
    - trim espaces
    """

    if not ingredients or not isinstance(ingredients, list):
        return []

    cleaned = []

    for ing in ingredients:
        if isinstance(ing, str):
            ing = ing.strip()

            if ing:
                cleaned.append(ing)

    return cleaned