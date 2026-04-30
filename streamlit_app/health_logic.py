"""health_logic.py — logique santé centralisée.

Corrections appliquées :
- CORRECTION point 9 : compute_health_score_oms() ajouté ici pour centraliser
  la logique. Était défini localement dans 01_detail_produit.py.
- health_score.py (calculate_health_score) est désormais obsolète et doit être
  supprimé : toute la logique passe par ce module.
"""

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class HealthProfile:
    """Préférences utilisateur pour le tri santé.

    Aucun diagnostic médical n'est effectué. L'utilisateur choisit :
    - éventuellement une intention générale (objectif : équilibrée ou perte de poids)
    - à quel point il souhaite pénaliser le sucre et le sel.
    """

    goal: str = "equilibree"
    constraints: list[str] = field(default_factory=list)
    sugar_penalty: float = 0.0
    salt_penalty: float = 0.0


GOAL_CHOICES: list[tuple[str, str]] = [
    ("equilibree", "Alimentation équilibrée"),
    ("perte_poids", "Perte de poids"),
]

CONSTRAINT_CHOICES: list[tuple[str, str]] = [
    ("diabete", "Diabète (limiter le sucre)"),
    ("hypertension", "Hypertension (limiter le sel)"),
]


def _nutriscore_to_numeric(series: pd.Series) -> pd.Series:
    """Convertit un NutriScore (A-E) en score numérique (A=5..E=1, sinon 0)."""
    mapping = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}
    return series.fillna("").astype(str).str.upper().map(mapping).fillna(0.0)


def _compute_weights(profile: HealthProfile) -> tuple[float, float, float]:
    """Détermine les coefficients (alpha, beta, gamma) selon les préférences.

    alpha : importance fixe du NutriScore
    beta  : coefficient appliqué au sucre (g/100g), dépend du curseur utilisateur
    gamma : coefficient appliqué au sel (g/100g), dépend du curseur utilisateur

    Les coefficients beta/gamma sont négatifs (on pénalise sucre/sel élevés).
    """
    alpha = 2.0
    beta = -float(profile.sugar_penalty)
    gamma = -float(profile.salt_penalty)

    if profile.goal == "perte_poids":
        beta *= 1.5
        gamma *= 1.5
    elif profile.goal == "equilibree":
        alpha *= 1.5

    return alpha, beta, gamma


def compute_personalized_scores(df: pd.DataFrame, profile: HealthProfile) -> pd.Series:
    """Calcule un score santé personnalisé par produit.

    Score relatif/comparatif utilisé pour trier les produits selon les
    préférences utilisateur (curseurs sucre/sel, objectif).

    Formule : S = alpha * score_nutri + beta * sucre_100g + gamma * sel_100g
    """
    if df.empty:
        return pd.Series([], index=df.index, dtype="float64")

    alpha, beta, gamma = _compute_weights(profile)

    nutri = _nutriscore_to_numeric(df["nutriscore_grade"])
    sugars = pd.to_numeric(df["sugars_100g"], errors="coerce").fillna(0.0)
    salt = pd.to_numeric(df["salt_100g"], errors="coerce").fillna(0.0)

    score = alpha * nutri + beta * sugars + gamma * salt
    return score.astype("float64")


def compute_health_score_oms(sugar, salt, fat_sat, fiber, proteins, nova, nutriscore) -> float:
    """Score santé absolu sur 100, inspiré des recommandations OMS.

    Utilisé pour l'affichage d'une valeur absolue sur la page détail produit.
    Ce score est DIFFÉRENT de compute_personalized_scores :
    - ici : valeur fixe /100 affichée à l'écran pour un seul produit
    - compute_personalized_scores : score relatif pour comparer et trier plusieurs produits

    CORRECTION point 9 : centralisé ici depuis 01_detail_produit.py pour éviter
    la duplication de logique.
    """
    score = 100.0

    try:
        if pd.notna(sugar):
            s = float(sugar)
            score -= 0 if s <= 5 else 5 if s <= 10 else 12 if s <= 20 else 18 if s <= 25 else 25
            score -= min((s / 25.0) * 2, 6)
            score -= min(s / 50.0, 2)
    except (TypeError, ValueError):
        pass

    try:
        if pd.notna(salt):
            s = float(salt)
            score -= 0 if s <= 0.3 else 4 if s <= 0.6 else 10 if s <= 1.2 else 15 if s <= 1.5 else 22
            score -= min((s / 5.0) * 3, 6)
    except (TypeError, ValueError):
        pass

    try:
        if pd.notna(fat_sat):
            f = float(fat_sat)
            score -= 0 if f <= 1.5 else 4 if f <= 3 else 9 if f <= 5 else 16 if f <= 10 else 24
            score -= min((f / 22.0) * 3, 6)
    except (TypeError, ValueError):
        pass

    try:
        if pd.notna(fiber):
            f = float(fiber)
            score += 10 if f >= 6 else 5 if f >= 3 else 2 if f > 0 else 0
            score += min((f / 25.0) * 2, 5)
    except (TypeError, ValueError):
        pass

    try:
        if pd.notna(proteins):
            p = float(proteins)
            score += 4 if p >= 10 else 2 if p >= 5 else 0
    except (TypeError, ValueError):
        pass

    try:
        if pd.notna(nova):
            n = int(nova)
            score -= 8 if n == 4 else 3 if n == 3 else 1 if n == 2 else 0
    except (TypeError, ValueError):
        pass

    try:
        ns = str(nutriscore).upper()
        score += {"A": 8, "B": 5, "C": 0, "D": -6, "E": -12}.get(ns, 0)
    except Exception:
        pass

    return round(max(0.0, min(100.0, score)), 2)
