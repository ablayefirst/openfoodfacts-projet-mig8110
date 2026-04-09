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

    # Logique simple non médicale :
    # - pour "perte de poids" on accentue la pénalisation sucre/sel
    # - pour "équilibrée" on renforce un peu le poids du NutriScore
    if profile.goal == "perte_poids":
        beta *= 1.5
        gamma *= 1.5
    elif profile.goal == "equilibree":
        alpha *= 1.5

    return alpha, beta, gamma


def compute_personalized_scores(df: pd.DataFrame, profile: HealthProfile) -> pd.Series:
    """Calcule un score santé personnalisé par produit.

    Le score est de la forme :
        S = alpha * score_nutri + beta * sucre_100g + gamma * sel_100g
    avec beta, gamma négatifs (on pénalise sucre/sel élevés).
    """

    if df.empty:
        return pd.Series([], index=df.index, dtype="float64")

    alpha, beta, gamma = _compute_weights(profile)

    nutri = _nutriscore_to_numeric(df["nutriscore_grade"])
    sugars = pd.to_numeric(df["sugars_100g"], errors="coerce").fillna(0.0)
    salt = pd.to_numeric(df["salt_100g"], errors="coerce").fillna(0.0)

    score = alpha * nutri + beta * sugars + gamma * salt
    return score.astype("float64")
