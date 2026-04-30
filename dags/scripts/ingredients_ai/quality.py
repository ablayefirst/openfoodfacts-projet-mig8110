import re


# =========================
# 🔤 NORMALIZE TEXT
# =========================
def normalize_text(text):
    if not text:
        return ""

    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)

    return text


# =========================
# 🚫 SPECIAL CHAR CHECK
# =========================
def has_special_chars(text):
    return bool(re.search(r"[^a-z0-9\s\-\(\)]", text))


# =========================
# 🚫 NOISE DETECTION
# =========================
def contains_noise_word(text):
    noise_words = {
        "www", "http", "barcode", "scan",
        "call", "distributed", "store",
        "product", "made", "facility"
    }

    words = re.findall(r"\b\w+\b", text)
    return any(word in noise_words for word in words)


# =========================
# 📊 EMBEDDING SCORE (CORE)
# =========================
def compute_embedding_score(total, matched):
    if total == 0:
        return 0

    return (matched / total) * 100


# =========================
# 📊 PENALTY SCORE
# =========================
def compute_penalty(ingredients):
    penalty = 0

    for ing in ingredients:

        if not isinstance(ing, str):
            penalty += 10
            continue

        ing = normalize_text(ing)

        if not ing:
            penalty += 10
            continue

        if has_special_chars(ing):
            penalty += 10

        if contains_noise_word(ing):
            penalty += 15

        if len(ing.split()) > 10:
            penalty += 5

        if any(c.isdigit() for c in ing):
            penalty += 5

        if "_" in ing:
            penalty += 5

    return penalty


# =========================
# 📊 FINAL QUALITY SCORE
# =========================
def compute_quality_score(total, matched, ingredients=None):
    """
    Score final basé sur :
    - embedding (principal)
    - pénalités heuristiques
    """

    # 🔥 score principal
    score = compute_embedding_score(total, matched)

    # 🔥 pénalités
    if ingredients:
        penalty = compute_penalty(ingredients)
        score -= penalty

    return max(round(score, 2), 0)