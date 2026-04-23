import base64
from pathlib import Path

import streamlit as st


MENU_ITEMS = [
    "Dashboard",
    "Tendances",
    "Favoris",
    "Admin",
]

APP_DIR = Path(__file__).resolve().parent
LOGO_PATH = APP_DIR / "static" / "logo" / "logo_V2.png"


def _logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""

    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _menu_style() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] {display: none !important;}
        [data-testid="stSidebar"] {display: none !important;}
        [data-testid="collapsedControl"] {display: none !important;}

        .top-menu-wrap {
            margin: 0.2rem 0 1rem;
            padding: 0.8rem;
            border: 1px solid rgba(15, 118, 110, 0.22);
            border-radius: 16px;
            background:
                radial-gradient(340px 120px at 5% 0%, rgba(20, 184, 166, 0.14), transparent 90%),
                radial-gradient(360px 140px at 85% 100%, rgba(245, 158, 11, 0.14), transparent 90%),
                #ffffff;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.07);
        }

        .top-menu-title {
            margin: 0 0 0.45rem;
            font-size: 0.82rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            font-weight: 700;
            color: #0f766e;
        }

        .top-brand-title {
            margin: 0;
            color: #0f172a;
            font-size: 1.7rem;
            font-weight: 800;
            line-height: 1.05;
        }

        .top-brand-subtitle {
            margin: 0.25rem 0 0;
            color: #475569;
            font-size: 0.92rem;
        }

        /* Style des boutons du menu avec la meme palette que top-menu-wrap */
        div[data-testid="stButton"] > button {
            border-radius: 12px;
            font-weight: 700;
            border: 1px solid rgba(15, 118, 110, 0.25);
            transition: all 0.18s ease;
        }

        div[data-testid="stButton"] > button[kind="secondary"] {
            color: #0f766e;
            background: rgba(20, 184, 166, 0.08);
        }

        div[data-testid="stButton"] > button[kind="secondary"]:hover {
            border-color: rgba(245, 158, 11, 0.45);
            background: rgba(245, 158, 11, 0.12);
            color: #0f172a;
        }

        div[data-testid="stButton"] > button[kind="primary"] {
            color: #0f172a;
            border-color: rgba(15, 118, 110, 0.55);
            background:
                linear-gradient(135deg, rgba(20, 184, 166, 0.35), rgba(245, 158, 11, 0.3)),
                #ffffff;
            box-shadow: 0 4px 14px rgba(15, 118, 110, 0.2);
        }

        div[data-testid="stButton"] > button[kind="primary"]:hover {
            border-color: rgba(15, 118, 110, 0.8);
            box-shadow: 0 6px 16px rgba(15, 118, 110, 0.26);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_top_menu(current_page: str) -> None:
    st.session_state.active_page = current_page

    _menu_style()

    # Logo et titre dans le div avec le style top-menu-wrap
    logo_html = ""
    logo_src = _logo_data_uri()
    if logo_src:
        logo_html = f'<img src="{logo_src}" style="width: 104px; height: auto;" />'
    
    st.markdown(f"""
        <div class='top-menu-wrap'>
            <div style='display: flex; align-items: flex-start; gap: 1rem; margin-bottom: 1rem;'>
                <div style='flex-shrink: 0;'>
                    {logo_html}
                </div>
                <div>
                    <h1 class="top-brand-title">Application Santé & Nutrition</h1>
                    <p class="top-brand-subtitle">Analyse, comparaison et recommandations produits OpenFoodFacts</p>
                </div>
            </div>
       
    """, unsafe_allow_html=True)

    with st.container():
        menu_cols = st.columns(len(MENU_ITEMS))
        for i, label in enumerate(MENU_ITEMS):
            with menu_cols[i]:
                is_current = label == current_page
                if st.button(
                    label,
                    key=f"top_menu_{label}",
                    type="primary" if is_current else "secondary",
                    use_container_width=True,
                ):
                    st.session_state.active_page = label
                    if label == "Dashboard":
                        st.switch_page("main.py")
                    elif label == "Tendances":
                        st.switch_page("pages/02_insights.py")
                    elif label == "Favoris":
                        st.switch_page("pages/04_panier_favori.py")
                    elif label == "Admin":
                        st.switch_page("pages/06_admin.py")
                    else:
                        st.switch_page("main.py")

    st.markdown("</div>", unsafe_allow_html=True)
