import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from health_logic import HealthProfile, GOAL_CHOICES, CONSTRAINT_CHOICES
from top_menu import render_top_menu


st.set_page_config(page_title="Mon profil santé", layout="wide", initial_sidebar_state="collapsed")

render_top_menu("Mon profil santé")

st.title("Mon profil santé")

st.write(
    """Cette page ne fournit **aucun avis médical**.
    Vous indiquez simplement vos contraintes et vos préférences de tri.
    """
)

if "health_profile" not in st.session_state:
    st.session_state.health_profile = None
if "use_health_profile" not in st.session_state:
    st.session_state.use_health_profile = False

current_profile = st.session_state.health_profile

default_goal = GOAL_CHOICES[0][0]
default_constraints: list[str] = []
default_sugar = 0.0
default_salt = 0.0

if isinstance(current_profile, HealthProfile):
    default_goal = getattr(current_profile, "goal", default_goal)
    default_constraints = list(getattr(current_profile, "constraints", []))
    default_sugar = float(getattr(current_profile, "sugar_penalty", 0.0))
    default_salt = float(getattr(current_profile, "salt_penalty", 0.0))

constraint_codes = [code for code, _ in CONSTRAINT_CHOICES]
constraint_labels = {code: label for code, label in CONSTRAINT_CHOICES}

selected_constraints = st.multiselect(
    "Contraintes de santé (optionnel)",
    options=constraint_codes,
    default=[c for c in default_constraints if c in constraint_codes],
    format_func=lambda c: constraint_labels[c],
)

goal_codes = [code for code, _ in GOAL_CHOICES]
goal_labels = {code: label for code, label in GOAL_CHOICES}

selected_goal = st.radio(
    "Objectif général",
    options=goal_codes,
    index=goal_codes.index(default_goal) if default_goal in goal_codes else 0,
    format_func=lambda c: goal_labels[c],
    horizontal=True,
)

st.markdown("---")

diabete_selected = "diabete" in selected_constraints
hta_selected = "hypertension" in selected_constraints

sugar_penalty = default_sugar
salt_penalty = default_salt

if diabete_selected and not hta_selected:
    sugar_penalty = st.slider(
        "Importance de réduire le sucre (0 = pas important, 2 = très important)",
        min_value=0.0,
        max_value=2.0,
        step=0.1,
        value=default_sugar,
    )
elif hta_selected and not diabete_selected:
    salt_penalty = st.slider(
        "Importance de réduire le sel (0 = pas important, 2 = très important)",
        min_value=0.0,
        max_value=2.0,
        step=0.1,
        value=default_salt,
    )
else:
    sugar_penalty = st.slider(
        "Importance de réduire le sucre (0 = pas important, 2 = très important)",
        min_value=0.0,
        max_value=2.0,
        step=0.1,
        value=default_sugar,
    )
    salt_penalty = st.slider(
        "Importance de réduire le sel (0 = pas important, 2 = très important)",
        min_value=0.0,
        max_value=2.0,
        step=0.1,
        value=default_salt,
    )

if st.button("Enregistrer mes préférences"):
    st.session_state.health_profile = HealthProfile(
        goal=selected_goal,
        constraints=selected_constraints,
        sugar_penalty=sugar_penalty,
        salt_penalty=salt_penalty,
    )
    st.success("Préférences de tri enregistrées.")

st.markdown("---")

health_profile = st.session_state.health_profile

if health_profile is not None:
    label = (
        "Utiliser ces préférences pour trier les produits"
        if not st.session_state.use_health_profile
        else "Désactiver le tri personnalisé"
    )
    if st.button(label):
        st.session_state.use_health_profile = not st.session_state.use_health_profile
    if st.session_state.use_health_profile:
        st.caption("Tri personnalisé activé en fonction de vos curseurs sucre/sel.")
else:
    st.caption(
        "Ajustez les curseurs puis enregistrez pour activer le tri personnalisé."
    )

st.markdown("---")
