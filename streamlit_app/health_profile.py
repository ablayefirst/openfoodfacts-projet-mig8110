from dataclasses import dataclass
from typing import List, Sequence

import pandas as pd
import streamlit as st


@dataclass
class HealthProfile:
    """Profil santé utilisateur stocké en session Streamlit.

    Attributes
    ----------
    goal: objectif principal (codes possibles : "equilibree", "perte_poids",
        "reduire_sucre", "reduire_sel").
    constraints: liste de contraintes de santé (ex. "diabete", "hypertension").
    """

    goal: str
    constraints: List[str]


# Codes + libellés utilisés dans l'UI
GOAL_CHOICES: Sequence[tuple[str, str]] = [
    ("equilibree", "Alimentation équilibrée"),
    ("perte_poids", "Perte de poids"),
    ("reduire_sucre", "Réduction du sucre"),
    ("reduire_sel", "Réduction du sel"),
]

CONSTRAINT_CHOICES: Sequence[tuple[str, str]] = [
    ("diabete", "Diabète (limiter sucre)"),
    ("hypertension", "Hypertension (limiter sel)"),
]


def get_default_profile() -> HealthProfile:
    """Profil par défaut : alimentation équilibrée sans contrainte explicite."""

    return HealthProfile(goal="equilibree", constraints=[])


def _nutriscore_to_numeric(series: pd.Series) -> pd.Series:
    """Convertit un NutriScore (A-E) en score numérique (A=5..E=1, sinon 0)."""

    mapping = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}
    return series.fillna("").astype(str).str.upper().map(mapping).fillna(0.0)


def _compute_weights(profile: HealthProfile) -> tuple[float, float, float]:
    """Détermine les coefficients (alpha, beta, gamma) selon le profil.

    alpha : importance du NutriScore
    beta  : coefficient appliqué au sucre (g/100g)
    gamma : coefficient appliqué au sel (g/100g)
    Les coefficients beta/gamma sont négatifs (on pénalise sucre/sel élevés).
    """

    # Poids de base : NutriScore important, sucre/sel modérément pénalisés
    alpha = 2.0
    beta = -1.0
    gamma = -1.0

    goal = profile.goal
    constraints = set(profile.constraints or [])

    # Objectifs
    if goal == "reduire_sucre":
        beta *= 2.0  # pénalise plus fortement le sucre
    elif goal == "reduire_sel":
        gamma *= 2.0  # pénalise plus fortement le sel
    elif goal == "perte_poids":
        # pour la perte de poids, on accentue sucre et sel
        beta *= 1.5
        gamma *= 1.5
    elif goal == "equilibree":
        # on renforce un peu l'importance du NutriScore global
        alpha *= 1.5

    # Contraintes médicales
    if "diabete" in constraints:
        beta *= 1.5
    if "hypertension" in constraints:
        gamma *= 1.5

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


def show_health_profile_page() -> None:
    """Affiche et gère la page Streamlit "Mon profil santé".

    - Choix des contraintes de santé
    - Objectif principal (ajusté selon les contraintes)
    - Enregistrement du profil dans st.session_state.health_profile
    - Bouton d'activation/désactivation du tri personnalisé
    """

    st.title("Mon profil santé")

    if "health_profile" not in st.session_state:
        st.session_state.health_profile = None
    if "use_health_profile" not in st.session_state:
        st.session_state.use_health_profile = False

    current_profile = st.session_state.health_profile

    constraint_codes = [code for code, _ in CONSTRAINT_CHOICES]
    constraint_labels = {code: label for code, label in CONSTRAINT_CHOICES}

    default_constraints: list[str] = []
    if isinstance(current_profile, HealthProfile):
        default_constraints = [c for c in current_profile.constraints if c in constraint_codes]

    selected_constraints = st.multiselect(
        "Contraintes de santé",
        options=constraint_codes,
        default=default_constraints,
        format_func=lambda c: constraint_labels[c],
    )

    goal_codes_all = [code for code, _ in GOAL_CHOICES]
    goal_labels = {code: label for code, label in GOAL_CHOICES}

    # Filtrage des objectifs disponibles en fonction des contraintes
    diabete_selected = "diabete" in selected_constraints
    hta_selected = "hypertension" in selected_constraints

    goal_codes = goal_codes_all.copy()
    imposed_goal = None

    if diabete_selected and not hta_selected:
        # Diabète → on force "réduction du sucre" et on retire "réduction du sel"
        imposed_goal = "reduire_sucre"
        goal_codes = [c for c in goal_codes_all if c != "reduire_sel"]
    elif hta_selected and not diabete_selected:
        # Hypertension → on force "réduction du sel" et on retire "réduction du sucre"
        imposed_goal = "reduire_sel"
        goal_codes = [c for c in goal_codes_all if c != "reduire_sucre"]

    if "hp_goal" not in st.session_state:
        if isinstance(current_profile, HealthProfile) and current_profile.goal in goal_codes:
            st.session_state.hp_goal = current_profile.goal
        elif imposed_goal is not None:
            st.session_state.hp_goal = imposed_goal
        else:
            st.session_state.hp_goal = goal_codes[0]
    else:
        # Si un objectif imposé est défini, on le sélectionne par défaut
        if imposed_goal is not None:
            st.session_state.hp_goal = imposed_goal
        # Si l'objectif courant n'est plus dans les options (filtré), on bascule sur l'imposé ou le premier
        elif st.session_state.hp_goal not in goal_codes:
            st.session_state.hp_goal = imposed_goal or goal_codes[0]

    selected_goal = st.radio(
        "Objectif principal",
        options=goal_codes,
        key="hp_goal",
        format_func=lambda c: goal_labels[c],
        horizontal=True,
    )

    if st.button("Enregistrer mon profil"):
        st.session_state.health_profile = HealthProfile(
            goal=selected_goal,
            constraints=selected_constraints,
        )
        st.success("Profil santé enregistré.")

    st.markdown("---")

    health_profile = st.session_state.health_profile

    if health_profile is not None:
        label = (
            "Voir des alternatives plus saines pour moi"
            if not st.session_state.use_health_profile
            else "Désactiver les recommandations personnalisées"
        )
        if st.button(label):
            st.session_state.use_health_profile = not st.session_state.use_health_profile
        if st.session_state.use_health_profile:
            st.caption("Tri personnalisé activé en fonction de votre profil santé.")
    else:
        st.caption(
            "Définissez votre profil dans la page 'Mon profil santé' pour obtenir des recommandations personnalisées."
        )
