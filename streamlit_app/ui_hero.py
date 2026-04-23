from html import escape

import streamlit as st


def render_page_hero(kicker: str, title: str, subtitle: str) -> None:
    """Render a shared page hero with the project visual style."""
    st.markdown(
        """
        <style>
        .page-hero {
            margin: 0.5rem 0 1.2rem;
            padding: 1rem 1.4rem 0.9rem;
            border: 1px solid rgba(15, 118, 110, 0.22);
            border-radius: 16px;
            background:
                radial-gradient(340px 120px at 5% 0%, rgba(20, 184, 166, 0.12), transparent 90%),
                radial-gradient(360px 140px at 85% 100%, rgba(245, 158, 11, 0.12), transparent 90%),
                #ffffff;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
        }

        .page-hero-kicker {
            margin: 0 0 2px;
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #0f766e;
        }

        .page-hero-title {
            margin: 0;
            font-size: 1.6rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.1;
        }

        .page-hero-subtitle {
            margin: 0.3rem 0 0;
            font-size: 0.9rem;
            color: #475569;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="page-hero">
            <p class="page-hero-kicker">{escape(kicker)}</p>
            <h2 class="page-hero-title">{escape(title)}</h2>
            <p class="page-hero-subtitle">{escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
