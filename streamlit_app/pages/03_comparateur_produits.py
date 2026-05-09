import sys
import warnings
from pathlib import Path
from html import escape

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db_connection import get_connection
from top_menu import render_top_menu
from ui_hero import render_page_hero

st.set_page_config(page_title="Comparateur de produits", layout="wide", initial_sidebar_state="collapsed")

render_top_menu("Dashboard")

# ─── CSS global de la page ────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* Carte produit comparateur */
    .comp-card {
        border: 1px solid rgba(15,118,110,0.22);
        border-radius: 16px;
        padding: 1.2rem 1.1rem 1rem;
        background:
            radial-gradient(280px 100px at 5% 0%, rgba(20,184,166,0.10), transparent 90%),
            radial-gradient(300px 120px at 90% 100%, rgba(245,158,11,0.10), transparent 90%),
            #ffffff;
        box-shadow: 0 6px 18px rgba(15,23,42,0.06);
        margin-bottom: 1rem;
        height: 100%;
    }
    .comp-card h3 {
        margin: 0 0 0.3rem;
        font-size: 1.05rem;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.3;
        word-break: break-word;
    }
    .comp-card .subtitle {
        font-size: 0.78rem;
        color: #64748b;
        margin-bottom: 0.8rem;
    }
    /* Badge NutriScore */
    .nutri-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-weight: 800;
        font-size: 0.85rem;
        letter-spacing: 0.04em;
    }
    .nutri-a { background:#1a7f37; color:#fff; }
    .nutri-b { background:#85c341; color:#fff; }
    .nutri-c { background:#f7c948; color:#1a1a1a; }
    .nutri-d { background:#ef8c14; color:#fff; }
    .nutri-e { background:#e63e11; color:#fff; }
    .nutri-na { background:#cbd5e1; color:#475569; }
    /* Badge NOVA */
    .nova-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.82rem;
    }
    .nova-1 { background:#1a7f37; color:#fff; }
    .nova-2 { background:#85c341; color:#fff; }
    .nova-3 { background:#ef8c14; color:#fff; }
    .nova-4 { background:#e63e11; color:#fff; }
    .nova-na { background:#cbd5e1; color:#475569; }
    /* Section critère */
    .crit-label {
        font-size: 0.78rem;
        font-weight: 600;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 2px;
    }
    .crit-value {
        font-size: 0.95rem;
        font-weight: 700;
        color: #0f172a;
    }
    .crit-best {
        color: #0f766e;
        font-size: 0.95rem;
        font-weight: 700;
    }
    .crit-worst {
        color: #b91c1c;
        font-size: 0.95rem;
        font-weight: 700;
    }
    /* Barre nutritionnelle */
    .nutr-bar-wrap {
        background: #f1f5f9;
        border-radius: 999px;
        height: 7px;
        width: 100%;
        margin: 3px 0 8px;
    }
    .nutr-bar-fill {
        height: 7px;
        border-radius: 999px;
    }
    /* Carte meilleur choix */
    .best-card {
        border: 2px solid rgba(15,118,110,0.45);
        border-radius: 16px;
        padding: 1.2rem 1.4rem;
        background:
            radial-gradient(340px 120px at 5% 0%, rgba(20,184,166,0.18), transparent 90%),
            radial-gradient(360px 140px at 85% 100%, rgba(245,158,11,0.15), transparent 90%),
            #ffffff;
        box-shadow: 0 8px 24px rgba(15,118,110,0.12);
        margin-top: 0.5rem;
    }
    .best-card h4 { margin: 0 0 0.4rem; color: #0f766e; font-size: 1.15rem; font-weight: 800; }
    .best-card p  { margin: 0.15rem 0; font-size: 0.95rem; color: #0f172a; }
    .score-pill {
        display: inline-block;
        padding: 0.18rem 0.48rem;
        border-radius: 999px;
        font-size: 0.76rem;
        font-weight: 800;
        color: #0f766e;
        background: #ccfbf1;
        border: 1px solid rgba(15,118,110,0.18);
        margin-bottom: 0.45rem;
    }
    .score-detail-list {
        margin: 0.45rem 0 0;
        padding-left: 1.1rem;
        color: #334155;
        font-size: 0.9rem;
    }
    .score-detail-list li { margin: 0.16rem 0; }
    /* Titre section critère */
    .section-title {
        font-size: 0.8rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #0f766e;
        margin: 0.8rem 0 0.4rem;
        padding-bottom: 3px;
        border-bottom: 1px solid rgba(15,118,110,0.18);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

render_page_hero(
    kicker="Analyse comparative",
    title="Comparateur de produits",
    subtitle="Comparez cote a cote les profils nutritionnels de vos produits selectionnes.",
)

# ─── Vérification de la sélection ─────────────────────────────────────────────
if "compare_selection" not in st.session_state or not st.session_state.compare_selection:
    st.info("Aucun produit sélectionné. Retournez au Dashboard et cliquez sur **⚖️ Compare** sur 2 à 4 produits.")
    st.stop()

codes = [str(c) for c in st.session_state.compare_selection]

if len(codes) < 2:
    st.info("Sélectionnez au moins 2 produits pour comparer.")
    st.stop()

if len(codes) > 4:
    codes = codes[:4]
    st.warning("Seuls les 4 premiers produits sélectionnés sont comparés.")

# ─── Chargement des données ────────────────────────────────────────────────────
conn = get_connection()

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

placeholders = ",".join(["%s"] * len(codes))

QUERY = f"""
SELECT p.code_produit AS code,
       p.nom_produit   AS product_name,
       p.categorie_principale,
       p.nutrition_grade AS nutriscore_grade,
       p.nova_group,
       v.sugars_100g,
       v.salt_100g,
       v.saturated_fat_100g,
       v.fiber_100g,
       v.proteins_100g
FROM produit p
LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
WHERE p.code_produit IN ({placeholders})
"""

compare_df = pd.read_sql(QUERY, conn, params=tuple(codes))

if compare_df.empty:
    st.error("Impossible de charger les produits sélectionnés.")
    st.stop()

# ─── Sélecteur de mode de comparaison ─────────────────────────────────────────
MODE_OPTIONS = [
    "Vue complète",
    "NutriScore & NOVA",
    "Profil nutritionnel",
]

st.markdown(
    "<p style='font-size:0.82rem; font-weight:700; text-transform:uppercase; "
    "letter-spacing:0.05em; color:#0f766e; margin-bottom:0.4rem;'>"
    "Mode de comparaison</p>",
    unsafe_allow_html=True,
)
compare_mode = st.radio(
    label="Mode de comparaison",
    options=MODE_OPTIONS,
    index=0,
    horizontal=True,
    label_visibility="collapsed",
)

st.markdown("<div style='margin-bottom:1rem;'></div>", unsafe_allow_html=True)

# ─── Fonctions utilitaires ─────────────────────────────────────────────────────

NUTRI_COLORS = {"A": "nutri-a", "B": "nutri-b", "C": "nutri-c", "D": "nutri-d", "E": "nutri-e"}
NOVA_COLORS  = {"1": "nova-1", "2": "nova-2", "3": "nova-3", "4": "nova-4"}


def nutri_badge(grade) -> str:
    g = str(grade).strip().upper() if pd.notna(grade) else "N/A"
    css = NUTRI_COLORS.get(g, "nutri-na")
    return f"<span class='nutri-badge {css}'>{g}</span>"


def nova_badge(group) -> str:
    g = str(int(float(group))) if pd.notna(group) and str(group).strip() not in ("", "N/A", "nan") else "N/A"
    css = NOVA_COLORS.get(g, "nova-na")
    return f"<span class='nova-badge {css}'>NOVA {g}</span>"


def safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return float("nan")


def nutrient_bar(value: float, max_val: float, color: str) -> str:
    if pd.isna(value) or max_val <= 0:
        pct = 0
    else:
        pct = min(100, round(value / max_val * 100))
    return (
        f"<div class='nutr-bar-wrap'>"
        f"<div class='nutr-bar-fill' style='width:{pct}%; background:{color};'></div>"
        f"</div>"
    )


def fmt_g(val) -> str:
    f = safe_float(val)
    return f"{f:.2f} g" if not pd.isna(f) else "—"


def format_delta(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f} pts"


def nutriscore_bonus(grade) -> float:
    mapping = {"A": 8.0, "B": 5.0, "C": 0.0, "D": -6.0, "E": -12.0}
    return mapping.get(str(grade).strip().upper(), 0.0)


def compute_health_score_details(row) -> tuple[float, list[tuple[str, float, str]]]:
    """Calcule un score santé explicable sur 100."""

    score = 100.0
    details: list[tuple[str, float, str]] = []

    sugar = safe_float(row.get("sugars_100g"))
    if not pd.isna(sugar):
        penalty = 0.0
        if sugar <= 5:
            penalty = 0.0
        elif sugar <= 10:
            penalty = 5.0
        elif sugar <= 20:
            penalty = 12.0
        elif sugar <= 25:
            penalty = 18.0
        else:
            penalty = 25.0
        penalty += min((sugar / 25.0) * 2, 6)
        penalty += min(sugar / 50.0, 2)
        score -= penalty
        details.append(("Sucre", -penalty, f"{sugar:.1f} g/100g"))

    salt = safe_float(row.get("salt_100g"))
    if not pd.isna(salt):
        penalty = 0.0
        if salt <= 0.3:
            penalty = 0.0
        elif salt <= 0.6:
            penalty = 4.0
        elif salt <= 1.2:
            penalty = 10.0
        elif salt <= 1.5:
            penalty = 15.0
        else:
            penalty = 22.0
        penalty += min((salt / 5.0) * 3, 6)
        score -= penalty
        details.append(("Sel", -penalty, f"{salt:.1f} g/100g"))

    fat_sat = safe_float(row.get("saturated_fat_100g"))
    if not pd.isna(fat_sat):
        penalty = 0.0
        if fat_sat <= 1.5:
            penalty = 0.0
        elif fat_sat <= 3:
            penalty = 4.0
        elif fat_sat <= 5:
            penalty = 9.0
        elif fat_sat <= 10:
            penalty = 16.0
        else:
            penalty = 24.0
        penalty += min((fat_sat / 22.0) * 3, 6)
        score -= penalty
        details.append(("Graisses saturées", -penalty, f"{fat_sat:.1f} g/100g"))

    fiber = safe_float(row.get("fiber_100g"))
    if not pd.isna(fiber):
        bonus = 0.0
        if fiber >= 6:
            bonus += 10.0
        elif fiber >= 3:
            bonus += 5.0
        elif fiber > 0:
            bonus += 2.0
        bonus += min((fiber / 25.0) * 2, 5)
        score += bonus
        details.append(("Fibres", bonus, f"{fiber:.1f} g/100g"))

    proteins = safe_float(row.get("proteins_100g"))
    if not pd.isna(proteins):
        bonus = 4.0 if proteins >= 10 else 2.0 if proteins >= 5 else 0.0
        score += bonus
        details.append(("Protéines", bonus, f"{proteins:.1f} g/100g"))

    nova = safe_float(row.get("nova_group"))
    if not pd.isna(nova):
        nova_int = int(nova)
        penalty = 8.0 if nova_int == 4 else 3.0 if nova_int == 3 else 1.0 if nova_int == 2 else 0.0
        score -= penalty
        details.append(("NOVA", -penalty, f"groupe {nova_int}"))

    nutri_delta = nutriscore_bonus(row.get("nutriscore_grade"))
    score += nutri_delta
    details.append(("NutriScore", nutri_delta, str(row.get("nutriscore_grade") or "N/A").upper()))

    return round(max(0.0, min(100.0, score)), 2), details


def render_score_chart(score_df: pd.DataFrame):
    plot_df = score_df.sort_values("Score santé")
    fig, ax = plt.subplots(figsize=(7, max(2.8, 0.55 * len(plot_df))))
    max_score = score_df["Score santé"].max()
    colors = ["#0f766e" if value == max_score else "#94a3b8" for value in plot_df["Score santé"]]
    bars = ax.barh(plot_df["Produit"], plot_df["Score santé"], color=colors)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Score santé / 100")
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for bar in bars:
        value = bar.get_width()
        ax.text(min(value + 1.2, 98), bar.get_y() + bar.get_height() / 2, f"{value:.1f}", va="center", fontsize=9)
    fig.tight_layout()
    return fig


# Calcul des "meilleurs" et "pires" pour mise en évidence
def best_worst_idx(series: pd.Series, higher_is_better: bool):
    """Renvoie (best_idx, worst_idx) ou (None, None) si pas assez de valeurs."""
    valid = series.dropna()
    if len(valid) < 2:
        return None, None
    best = valid.idxmax() if higher_is_better else valid.idxmin()
    worst = valid.idxmin() if higher_is_better else valid.idxmax()
    return best, worst


score_rows = []
for idx, score_row in compare_df.iterrows():
    score_value, _ = compute_health_score_details(score_row)
    score_rows.append(
        {
            "Produit": str(score_row.get("product_name") or "Produit sans nom"),
            "Code": str(score_row.get("code")),
            "NutriScore": str(score_row.get("nutriscore_grade") or "N/A").upper(),
            "NOVA": safe_float(score_row.get("nova_group")),
            "Sucre": safe_float(score_row.get("sugars_100g")),
            "Sel": safe_float(score_row.get("salt_100g")),
            "Fibres": safe_float(score_row.get("fiber_100g")),
            "Protéines": safe_float(score_row.get("proteins_100g")),
            "Score santé": score_value,
        }
    )
score_df = pd.DataFrame(score_rows)


# ─── Cartes de comparaison ─────────────────────────────────────────────────────
cols = st.columns(len(compare_df))

# Pré-calcul meilleurs/pires pour chaque nutriment
nutrients_cfg = {
    "sugars_100g":        {"label": "Sucre",             "max": 50.0,  "color": "#f59e0b", "higher_better": False},
    "salt_100g":          {"label": "Sel",               "max": 25.0,  "color": "#ef4444", "higher_better": False},
    "saturated_fat_100g": {"label": "Graisses saturées", "max": 30.0,  "color": "#f97316", "higher_better": False},
    "fiber_100g":         {"label": "Fibres",            "max": 20.0,  "color": "#22c55e", "higher_better": True},
    "proteins_100g":      {"label": "Protéines",         "max": 50.0,  "color": "#3b82f6", "higher_better": True},
}

bw = {}
for col_key, cfg in nutrients_cfg.items():
    series = compare_df[col_key].apply(safe_float)
    bw[col_key] = best_worst_idx(series, cfg["higher_better"])

nutri_mapping = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
nutri_series = (
    compare_df["nutriscore_grade"].fillna("").astype(str).str.upper().map(nutri_mapping).fillna(0)
)
best_nutri_idx, worst_nutri_idx = best_worst_idx(nutri_series, higher_is_better=True)

nova_series = compare_df["nova_group"].apply(
    lambda x: -safe_float(x) if not pd.isna(safe_float(x)) else float("nan")
)
best_nova_idx, worst_nova_idx = best_worst_idx(nova_series, higher_is_better=True)

for col_obj, (idx, row) in zip(cols, compare_df.iterrows()):
    with col_obj:
        name = str(row["product_name"]) if pd.notna(row["product_name"]) else "—"
        code = str(row["code"])
        cat  = str(row.get("categorie_principale") or "autres")
        score_value = score_df.loc[score_df["Code"] == code, "Score santé"].iloc[0]

        card_html = (
            f"<div class='comp-card'>"
            f"<h3>{escape(name)}</h3>"
            f"<div class='subtitle'>Code&nbsp;{escape(code)} &nbsp;&middot;&nbsp; {escape(cat)}</div>"
            f"<span class='score-pill'>Score santé {score_value:.1f}/100</span>"
        )

        # ── NutriScore & NOVA ──────────────────────────────────────────
        if compare_mode in ("Vue complète", "NutriScore & NOVA"):
            ns_html = nutri_badge(row.get("nutriscore_grade"))
            nv_html = nova_badge(row.get("nova_group"))

            ns_hl = ""
            if best_nutri_idx is not None and idx == best_nutri_idx:
                ns_hl = " &nbsp;<span style='color:#0f766e;font-size:0.75rem;'>✔ meilleur</span>"
            elif worst_nutri_idx is not None and idx == worst_nutri_idx:
                ns_hl = " &nbsp;<span style='color:#b91c1c;font-size:0.75rem;'>⚠ moins bon</span>"

            nv_hl = ""
            if best_nova_idx is not None and idx == best_nova_idx:
                nv_hl = " &nbsp;<span style='color:#0f766e;font-size:0.75rem;'>✔ moins transformé</span>"
            elif worst_nova_idx is not None and idx == worst_nova_idx:
                nv_hl = " &nbsp;<span style='color:#b91c1c;font-size:0.75rem;'>⚠ ultra-transformé</span>"

            card_html += (
                f"<div class='section-title'>Classification</div>"
                f"<div style='margin-bottom:6px;'>"
                f"<span class='crit-label'>NutriScore&nbsp;</span>"
                f"{ns_html}{ns_hl}"
                f"</div>"
                f"<div style='margin-bottom:6px;'>"
                f"<span class='crit-label'>Groupe NOVA&nbsp;</span>"
                f"{nv_html}{nv_hl}"
                f"</div>"
            )

        # ── Profil nutritionnel ────────────────────────────────────────
        if compare_mode in ("Vue complète", "Profil nutritionnel"):
            card_html += "<div class='section-title'>Profil nutritionnel (pour 100 g)</div>"
            for col_key, cfg in nutrients_cfg.items():
                val = safe_float(row.get(col_key))
                bar = nutrient_bar(val, cfg["max"], cfg["color"])
                val_str = fmt_g(val) if not pd.isna(val) else "—"
                b_idx, w_idx = bw[col_key]
                hl_class = ""
                if b_idx is not None and idx == b_idx:
                    hl_class = "crit-best"
                elif w_idx is not None and idx == w_idx:
                    hl_class = "crit-worst"
                card_html += (
                    f"<div class='crit-label'>{cfg['label']}</div>"
                    f"<div class='{hl_class} crit-value'>{val_str}</div>"
                    f"{bar}"
                )

        card_html += "</div>"
        st.markdown(card_html, unsafe_allow_html=True)

        # Bouton vers détail produit
        if st.button("Détail", key=f"comp_detail_{code}", use_container_width=True):
            st.session_state.selected_code = code
            st.query_params["code"] = code
            st.switch_page("pages/01_detail_produit.py")

# ─── Résultat : meilleur choix selon le mode ─────────────────────────────────
st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)

best_row = None
reason = None

if compare_mode in ("Vue complète", "NutriScore & NOVA"):
    # Critère : NutriScore en priorité, NOVA en départage
    if nutri_series.max() > 0:
        # Si égalité NutriScore, départager par NOVA (moins transformé = meilleur)
        nova_num = compare_df["nova_group"].apply(safe_float)
        combined = nutri_series * 10 + nova_num.apply(lambda v: (5 - v) if not pd.isna(v) else 0)
        idx = combined.idxmax()
        best_row = compare_df.loc[idx]
        reason = "NutriScore (départage NOVA)"
    elif not nova_series.dropna().empty:
        idx = nova_series.idxmax()
        best_row = compare_df.loc[idx]
        reason = "Groupe NOVA"

elif compare_mode == "Profil nutritionnel":
    nutr_scores = pd.Series(
        {
            idx: score_df.loc[score_df["Code"] == str(row["code"]), "Score santé"].iloc[0]
            for idx, row in compare_df.iterrows()
        }
    )
    idx = nutr_scores.idxmax()
    best_row = compare_df.loc[idx]
    reason = "score santé explicable (sucre, sel, graisses, fibres, protéines, NOVA, NutriScore)"

if best_row is not None:
    name_b = str(best_row["product_name"]) if pd.notna(best_row["product_name"]) else "—"
    cat_b  = str(best_row.get("categorie_principale") or "autres")
    ns_b   = nutri_badge(best_row.get("nutriscore_grade"))
    nv_b   = nova_badge(best_row.get("nova_group"))
    best_score, best_details = compute_health_score_details(best_row)
    detail_items = "".join(
        f"<li><b>{escape(label)}:</b> {format_delta(delta)} ({escape(context)})</li>"
        for label, delta, context in best_details
    )

    st.markdown(
        f"<div class='best-card'>"
        f"<h4> Meilleur choix — mode <em>{compare_mode}</em></h4>"
        f"<p style='font-size:1.05rem;font-weight:800;color:#0f172a;margin-bottom:0.5rem;'>{escape(name_b)}</p>"
        f"<p><b>Score santé :</b> {best_score:.1f}/100</p>"
        f"<p><b>Catégorie :</b> {escape(cat_b)}</p>"
        f"<p><b>NutriScore :</b> {ns_b}</p>"
        f"<p><b>Groupe NOVA :</b> {nv_b}</p>"
        f"<p style='margin-top:0.6rem;font-size:0.8rem;color:#64748b;'>Critère : <em>{reason}</em></p>"
        f"<ul class='score-detail-list'>{detail_items}</ul>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown("## Synthèse comparative")
st.dataframe(
    score_df.sort_values("Score santé", ascending=False),
    use_container_width=True,
    hide_index=True,
    column_config={
        "Score santé": st.column_config.ProgressColumn(
            "Score santé",
            help="Score explicable sur 100. Plus la valeur est élevée, meilleur est le profil nutritionnel.",
            min_value=0,
            max_value=100,
            format="%.1f",
        ),
        "Sucre": st.column_config.NumberColumn("Sucre", format="%.2f g"),
        "Sel": st.column_config.NumberColumn("Sel", format="%.2f g"),
        "Fibres": st.column_config.NumberColumn("Fibres", format="%.2f g"),
        "Protéines": st.column_config.NumberColumn("Protéines", format="%.2f g"),
    },
)

st.pyplot(render_score_chart(score_df), use_container_width=True)
