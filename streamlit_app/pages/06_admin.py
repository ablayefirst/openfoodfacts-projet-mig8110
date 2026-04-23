import streamlit as st
import sys
from pathlib import Path

# Adjust path to import admin module
sys.path.insert(0, str(Path(__file__).parent.parent))

from admin import run_admin
from top_menu import render_top_menu

# Configuration
st.set_page_config(
    page_title="Admin",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Render top menu
render_top_menu("Admin")

# Run admin panel
run_admin()
