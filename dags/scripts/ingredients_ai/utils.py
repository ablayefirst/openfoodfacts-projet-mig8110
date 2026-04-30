# utils.py
import re


# ── Déduplication ─────────────────────────────────────────────────
def deduplicate_keep_order(items):
    seen, result = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ── Normalisation robuste ─────────────────────────────────────────
def normalize(ing: str) -> str:
    if not ing or not isinstance(ing, str):
        return ""

    ing = str(ing).lower().strip()
    ing = re.sub(r"\s+", " ", ing)

    return ing


# ── Nettoyage fort ────────────────────────────────────────────────
def clean_ingredient(ing: str) -> str:
    """
    Nettoyage avancé pour garantir une donnée propre
    """

    if not ing or not isinstance(ing, str):
        return ""

    ing = normalize(ing)

    # supprimer ponctuation inutile (mais garder % et parenthèses)
    ing = re.sub(r"[\,\;\:\.\!\?]+", "", ing)

    # réduire multi tirets
    ing = re.sub(r"[-]{2,}", "-", ing)

    # nettoyer espaces parenthèses
    ing = re.sub(r"\s*\(\s*", "(", ing)
    ing = re.sub(r"\s*\)\s*", ")", ing)

    # enlever espaces multiples
    ing = re.sub(r"\s+", " ", ing)

    return ing.strip()


# ── Réduction intelligente (NOUVEAU 🔥) ───────────────────────────
REDUCTION_WORDS = {
    "extract", "concentrate", "flavor", "flavour",
    "powder", "juice", "essence",
    "natural", "artificial"
}


def reduce_ingredient(ing: str) -> str:
    """
    Réduction minimale pour fallback intelligent
    """
    if not ing:
        return ""

    ing = clean_ingredient(ing)

    words = ing.split()

    # supprimer mots non essentiels
    filtered = [w for w in words if w not in REDUCTION_WORDS]

    # si tout supprimé → fallback
    if not filtered:
        return ing

    # garder max 2 mots
    return " ".join(filtered[:2])


# ── Mots parasites ────────────────────────────────────────────────
NOISE_WORDS = {
    "www", "http", "https", "barcode", "scan",
    "call", "distributed", "store", "product",
    "made", "facility", "manufactured",
}


def is_noise(ing: str) -> bool:
    words = re.findall(r"\b\w+\b", ing.lower())
    return any(w in NOISE_WORDS for w in words)


# ── Valeurs invalides ─────────────────────────────────────────────
INVALID_VALUES = {
    "", "?", "-", "--", "---",
    "n/a", "none", "null", "unknown",
}


# ── Validation ingrédient ─────────────────────────────────────────
def is_invalid(ing: str) -> bool:
    """
    Filtre les chaînes qui ne sont clairement pas des ingrédients.
    """

    if not ing or ing in INVALID_VALUES:
        return True

    if len(ing) < 2:
        return True

    # Trop long → probablement phrase
    if len(ing.split()) > 12:
        return True

    # Trop de chiffres
    digits = sum(c.isdigit() for c in ing)
    if digits > 4:
        return True

    # Caractères non autorisés
    if re.search(r"[^a-z0-9\s\-\(\)\%\']", ing):
        return True

    return False


# ── Nettoyage final ───────────────────────────────────────────────
def final_cleanup(ingredients: list) -> list:
    """
    Nettoyage final robuste :
    - clean_ingredient
    - suppression bruit
    - suppression invalides
    - déduplication ordre-stable
    """

    if not ingredients:
        return []

    cleaned, seen = [], set()

    for ing in ingredients:

        ing = clean_ingredient(ing)

        if not ing:
            continue

        if is_noise(ing):
            continue

        if is_invalid(ing):
            continue

        if ing in seen:
            continue

        seen.add(ing)
        cleaned.append(ing)

    return cleaned