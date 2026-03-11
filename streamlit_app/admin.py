import os
import math
import streamlit as st

from sqlalchemy import or_, cast, String
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, delete, insert, func

from db import SessionLocal
from models import (
    Product,
    Marque,
    Categorie,
    Ingredient,
    produit_categorie,
    produit_ingredient,
)


# =========================
# Helpers (Marque / Catégories / Ingrédients)
# =========================
def _split_csv(txt: str) -> list[str]:
    if not txt:
        return []
    parts = [p.strip() for p in txt.replace("|", ",").split(",")]
    return [p for p in parts if p]


def _get_or_create_marque(db, marque_nom: str | None) -> Marque | None:
    if not marque_nom:
        return None
    name = marque_nom.strip()
    if not name:
        return None

    obj = (
        db.execute(
            select(Marque)
            .where(func.lower(Marque.brands) == name.lower())
            .order_by(Marque.id_marque.asc())
        )
        .scalars()
        .first()
    )
    if obj:
        return obj

    obj = Marque(brands=name)
    db.add(obj)
    db.flush()
    return obj


def _get_or_create_categories(db, categories_txt: str | None) -> list[Categorie]:
    items = _split_csv(categories_txt or "")
    if not items:
        return []
    out: list[Categorie] = []
    for c in items:
        obj = (
            db.execute(
                select(Categorie)
                .where(func.lower(Categorie.categorie) == c.lower())
                .order_by(Categorie.id_categorie.asc())
            )
            .scalars()
            .first()
        )
        if not obj:
            obj = Categorie(categorie=c)
            db.add(obj)
            db.flush()
        out.append(obj)
    return out


def _get_or_create_ingredients(db, ingredients_txt: str | None) -> list[Ingredient]:
    items = _split_csv(ingredients_txt or "")
    if not items:
        return []
    out: list[Ingredient] = []
    for i in items:
        obj = (
            db.execute(
                select(Ingredient)
                .where(func.lower(Ingredient.ingredients_nom) == i.lower())
                .order_by(Ingredient.id_ingredient.asc())
            )
            .scalars()
            .first()
        )
        if not obj:
            obj = Ingredient(ingredients_nom=i)
            db.add(obj)
            db.flush()
        out.append(obj)
    return out


def _replace_product_categories(db, code_produit: str, categories: list[Categorie]) -> None:
    db.execute(
        delete(produit_categorie).where(produit_categorie.c.code_produit == code_produit)
    )
    if categories:
        db.execute(
            insert(produit_categorie),
            [{"code_produit": code_produit, "id_categorie": c.id_categorie} for c in categories],
        )


def _replace_product_ingredients(db, code_produit: str, ingredients: list[Ingredient]) -> None:
    db.execute(
        delete(produit_ingredient).where(produit_ingredient.c.code_produit == code_produit)
    )
    if ingredients:
        db.execute(
            insert(produit_ingredient),
            [{"code_produit": code_produit, "id_ingredient": i.id_ingredient} for i in ingredients],
        )


# =========================
# Auth Streamlit (session_state)
# =========================
def _login_ui():
    st.subheader("🔐 Admin - Connexion")

    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")

    with st.form("admin_login", clear_on_submit=False):
        u = st.text_input("Nom d'utilisateur")
        p = st.text_input("Mot de passe", type="password")
        ok = st.form_submit_button("Se connecter")

    if ok:
        if u == admin_user and p == admin_pass:
            st.session_state["admin_ok"] = True
            st.success("Connexion réussie ✅")
            st.rerun()
        else:
            st.error("Identifiants invalides ❌")


def _logout_ui():
    if st.sidebar.button("Logout"):
        st.session_state.pop("admin_ok", None)
        st.rerun()


# =========================
# Admin - Liste Produits
# =========================
def _products_list_ui():
    st.subheader("📦 Admin - Produits")

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        q = st.text_input(
            "Recherche (code exact si nombre / sinon texte)",
            value=st.session_state.get("admin_q", ""),
        )
    with c2:
        per_page = st.selectbox("Par page", [10, 25, 50, 100], index=1)
    with c3:
        page = st.number_input(
            "Page",
            min_value=1,
            value=int(st.session_state.get("admin_page", 1)),
            step=1,
        )

    st.session_state["admin_q"] = q
    st.session_state["admin_page"] = page

    db = SessionLocal()
    try:
        query_db = db.query(Product)

        qn = (q or "").strip()
        if qn:
            like = f"%{qn}%"
            if qn.isdigit():
                # code_produit est Text dans ton modèle
                query_db = query_db.filter(Product.code_produit == str(int(qn)))
            else:
                query_db = query_db.filter(
                    or_(
                        Product.nom_produit.ilike(like),
                        Product.brands.ilike(like),
                        Product.categories.ilike(like),
                        cast(Product.code_produit, String).ilike(like),
                    )
                )

        total = query_db.count()
        total_pages = max(1, math.ceil(total / per_page))
        if page > total_pages:
            page = total_pages

        products = (
            query_db.order_by(Product.code_produit.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        st.caption(f"Total: **{total}** | Pages: **{total_pages}** | Page: **{page}**")

        st.divider()
        if st.button("➕ Ajouter un produit"):
            st.session_state["admin_mode"] = "new"
            st.rerun()

        st.divider()

        for p in products:
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.write(f"**{p.code_produit}** — {p.nom_produit or ''}")
                st.caption(
                    f"NutriScore: {p.nutrition_grade or 'N/A'} | "
                    f"Nova: {p.nova_group or 'N/A'} | "
                    f"Marque: {p.brands or 'N/A'}"
                )
            with col2:
                if st.button("✏️ Modifier", key=f"edit_{p.code_produit}"):
                    st.session_state["admin_mode"] = "edit"
                    st.session_state["admin_code"] = p.code_produit
                    st.rerun()
            with col3:
                if st.button("🗑️ Supprimer", key=f"del_{p.code_produit}"):
                    st.session_state["admin_mode"] = "delete"
                    st.session_state["admin_code"] = p.code_produit
                    st.rerun()

    finally:
        db.close()


# =========================
# Admin - Form Produit (avec marque/catégories/ingrédients)
# =========================
def _product_form_ui(is_edit: bool, code: str | None = None):
    db = SessionLocal()
    p = None

    try:
        if is_edit:
            p = db.query(Product).filter(Product.code_produit == str(code)).first()
            if not p:
                st.error("Produit introuvable.")
                if st.button("⬅️ Retour"):
                    st.session_state["admin_mode"] = "list"
                    st.rerun()
                return

        st.subheader("✏️ Modifier un produit" if is_edit else "➕ Ajouter un produit")

        with st.form("product_form", clear_on_submit=False):
            code_val = st.text_input("Code produit", value=(p.code_produit if p else ""))
            name_val = st.text_input("Nom produit", value=((p.nom_produit or "") if p else ""))

            grade_val = st.text_input("Nutrition grade (A-E)", value=((p.nutrition_grade or "") if p else ""))
            nutri_score_val = st.text_input(
                "Nutriscore score (int)",
                value=(str(p.nutriscore_score) if p and p.nutriscore_score is not None else ""),
            )
            nova_val = st.text_input(
                "Nova group (int)",
                value=(str(p.nova_group) if p and p.nova_group is not None else ""),
            )

            url_val = st.text_input("URL", value=((p.url or "") if p else ""))
            image_url_val = st.text_input("Image URL", value=((p.image_url or "") if p else ""))

            # ✅ Champs relations (comme FastAPI)
            marque_nom = st.text_input("Marque", value=((p.brands or "") if p else ""))
            categories_txt = st.text_area(
                "Catégories (séparées par , ou |)",
                value=((p.categories or "") if p else ""),
                height=80,
            )
            ingredients_txt = st.text_area(
                "Ingrédients (séparés par , ou |)",
                value=((p.ingredients_text or "") if p else ""),
                height=80,
            )

            ok = st.form_submit_button("Enregistrer")

        if ok:
            try:
                if not code_val.strip():
                    st.error("Code produit obligatoire.")
                    return
                if not name_val.strip():
                    st.error("Nom produit obligatoire.")
                    return

                # NEW
                if not is_edit:
                    exists = db.query(Product).filter(Product.code_produit == code_val.strip()).first()
                    if exists:
                        st.error("Ce code produit existe déjà.")
                        return

                    p = Product(code_produit=code_val.strip())
                    db.add(p)

                # UPDATE champs simples
                p.nom_produit = name_val.strip()
                p.nutrition_grade = (grade_val.strip()[:1].upper() if grade_val.strip() else None)
                p.nutriscore_score = (int(nutri_score_val) if nutri_score_val.strip() else None)
                p.nova_group = (int(nova_val) if nova_val.strip() else None)
                p.url = (url_val.strip() or None)
                p.image_url = (image_url_val.strip() or None)

                # ✅ Marque / Catégories / Ingrédients (relations)
                m = _get_or_create_marque(db, marque_nom)
                p.id_marque = (m.id_marque if m else None)

                db.flush()

                cats = _get_or_create_categories(db, categories_txt)
                ings = _get_or_create_ingredients(db, ingredients_txt)

                _replace_product_categories(db, p.code_produit, cats)
                _replace_product_ingredients(db, p.code_produit, ings)

                db.commit()
                st.success("✅ Enregistré.")
                st.session_state["admin_mode"] = "list"
                st.rerun()

            except (ValueError, SQLAlchemyError) as e:
                db.rollback()
                st.error(f"Erreur enregistrement: {e}")

        if st.button("⬅️ Retour"):
            st.session_state["admin_mode"] = "list"
            st.rerun()

    finally:
        db.close()


# =========================
# Admin - Delete confirm
# =========================
def _delete_ui(code: str):
    st.subheader(f"🗑️ Supprimer produit {code}")

    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.code_produit == str(code)).first()
        if not p:
            st.error("Produit introuvable.")
            st.session_state["admin_mode"] = "list"
            st.rerun()
            return

        st.warning("Cette action est irréversible.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ Confirmer suppression"):
                try:
                    # Nettoyage associations avant delete (recommandé)
                    db.execute(delete(produit_categorie).where(produit_categorie.c.code_produit == str(code)))
                    db.execute(delete(produit_ingredient).where(produit_ingredient.c.code_produit == str(code)))

                    db.delete(p)
                    db.commit()
                    st.success("Supprimé ✅")
                    st.session_state["admin_mode"] = "list"
                    st.rerun()
                except SQLAlchemyError as e:
                    db.rollback()
                    st.error(f"Erreur suppression: {e}")
        with c2:
            if st.button("❌ Annuler"):
                st.session_state["admin_mode"] = "list"
                st.rerun()
    finally:
        db.close()


# =========================
# Entry point
# =========================
def run_admin():
    if not st.session_state.get("admin_ok"):
        _login_ui()
        return

    st.sidebar.success("Connecté en admin ✅")
    _logout_ui()

    mode = st.session_state.get("admin_mode", "list")
    if mode == "list":
        _products_list_ui()
    elif mode == "new":
        _product_form_ui(is_edit=False)
    elif mode == "edit":
        _product_form_ui(is_edit=True, code=st.session_state.get("admin_code"))
    elif mode == "delete":
        _delete_ui(code=st.session_state.get("admin_code"))
    else:
        st.session_state["admin_mode"] = "list"
        st.rerun()