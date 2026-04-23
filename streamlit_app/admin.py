import os
import math
from datetime import datetime, UTC
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
    RejectedProductReview,
    ManualProductCorrection,
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


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


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


def _get_all_categories(db) -> list[Categorie]:
    return (
        db.execute(
            select(Categorie).order_by(Categorie.categorie.asc())
        )
        .scalars()
        .all()
    )


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


def _get_selected_categories_for_product(db, code_produit: str) -> list[str]:
    rows = db.execute(
        select(Categorie.categorie)
        .select_from(
            produit_categorie.join(
                Categorie,
                produit_categorie.c.id_categorie == Categorie.id_categorie
            )
        )
        .where(produit_categorie.c.code_produit == code_produit)
        .order_by(Categorie.categorie.asc())
    ).all()

    return [row[0] for row in rows]


def _get_active_correction_for_code(db, code_produit: str) -> ManualProductCorrection | None:
    return (
        db.execute(
            select(ManualProductCorrection)
            .where(
                ManualProductCorrection.code_produit == code_produit,
                ManualProductCorrection.is_active.is_(True),
            )
            .order_by(ManualProductCorrection.updated_at.desc(), ManualProductCorrection.correction_id.desc())
        )
        .scalars()
        .first()
    )


def _format_issue_list(issues) -> str:
    if isinstance(issues, list):
        return ", ".join(str(issue) for issue in issues if issue)
    if isinstance(issues, str):
        return issues
    return ""


def _payload_field_value(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            formatted = ", ".join(str(item) for item in value if item not in {None, ""})
            if formatted:
                return formatted
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _manual_or_source_value(manual_value, source_value: str) -> str:
    if manual_value is None:
        return source_value
    text = str(manual_value).strip()
    return text if text else source_value


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
    if st.button("Logout", type="secondary"):
        st.session_state.pop("admin_ok", None)
        st.session_state.pop("admin_mode", None)
        st.session_state.pop("admin_code", None)
        st.session_state.pop("admin_rejected_id", None)
        st.session_state.pop("admin_q", None)
        st.session_state.pop("admin_page", None)
        st.session_state.pop("reject_q", None)
        st.session_state.pop("reject_status", None)
        st.session_state.pop("admin_flash", None)
        st.rerun()


def _show_admin_flash():
    flash = st.session_state.pop("admin_flash", None)
    if not flash:
        return

    level = flash.get("level", "success")
    message = flash.get("message", "")
    if not message:
        return

    if level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.success(message)


# =========================
# Admin - Liste Produits
# =========================
def _products_list_ui():
    st.subheader("📦 Admin - Produits")
    nav1, nav2 = st.columns([1, 1])
    with nav1:
        st.button("📦 Produits", disabled=True, use_container_width=True)
    with nav2:
        if st.button("🛠️ Rejets à corriger", use_container_width=True):
            st.session_state["admin_mode"] = "reject_list"
            st.rerun()

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
                query_db = query_db.filter(Product.code_produit == qn)
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
            st.session_state["admin_page"] = page

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
            st.session_state.pop("admin_code", None)
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
                    st.session_state["admin_code"] = str(p.code_produit)
                    st.rerun()

            with col3:
                if st.button("🗑️ Supprimer", key=f"del_{p.code_produit}"):
                    st.session_state["admin_mode"] = "delete"
                    st.session_state["admin_code"] = str(p.code_produit)
                    st.rerun()

    finally:
        db.close()


# =========================
# Admin - Liste des rejets
# =========================
def _rejected_products_list_ui():
    st.subheader("🛠️ Produits rejetés à corriger")
    _show_admin_flash()
    nav1, nav2 = st.columns([1, 1])
    with nav1:
        if st.button("📦 Produits", use_container_width=True):
            st.session_state["admin_mode"] = "list"
            st.rerun()
    with nav2:
        st.button("🛠️ Rejets à corriger", disabled=True, use_container_width=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        q = st.text_input(
            "Recherche code / nom / marque",
            value=st.session_state.get("reject_q", ""),
        )
    with c2:
        status_filter = st.selectbox(
            "Statut",
            ["all", "pending", "in_review", "corrected", "resolved", "ignored"],
            index=["all", "pending", "in_review", "corrected", "resolved", "ignored"].index(
                st.session_state.get("reject_status", "all")
            ),
        )

    st.session_state["reject_q"] = q
    st.session_state["reject_status"] = status_filter

    db = SessionLocal()
    try:
        query_db = db.query(RejectedProductReview)

        qn = (q or "").strip()
        if qn:
            like = f"%{qn}%"
            query_db = query_db.filter(
                or_(
                    RejectedProductReview.code_produit.ilike(like),
                    RejectedProductReview.product_name.ilike(like),
                    RejectedProductReview.brands.ilike(like),
                )
            )

        if status_filter != "all":
            query_db = query_db.filter(RejectedProductReview.review_status == status_filter)

        rejected_products = (
            query_db.order_by(RejectedProductReview.created_at.desc(), RejectedProductReview.rejected_id.desc())
            .limit(200)
            .all()
        )

        st.caption(f"Résultats: **{len(rejected_products)}**")
        st.divider()

        if not rejected_products:
            st.info("Aucun produit rejeté à afficher.")
            return

        for rejected in rejected_products:
            correction = _get_active_correction_for_code(db, rejected.code_produit)
            col1, col2 = st.columns([4, 1])

            with col1:
                st.write(f"**{rejected.code_produit}** — {rejected.product_name or 'Sans nom'}")
                st.caption(
                    f"Marque: {rejected.brands or 'N/A'} | "
                    f"Issues: {_format_issue_list(rejected.quality_issues) or 'N/A'} | "
                    f"Rejet: {rejected.review_status}"
                )
                if correction:
                    st.caption(
                        f"Correction active: {correction.correction_status} | "
                        f"Par: {correction.corrected_by or 'N/A'}"
                    )

            with col2:
                if st.button("✏️ Corriger", key=f"reject_edit_{rejected.rejected_id}"):
                    st.session_state["admin_mode"] = "reject_edit"
                    st.session_state["admin_rejected_id"] = int(rejected.rejected_id)
                    st.rerun()

    except SQLAlchemyError as e:
        st.error(f"Erreur chargement rejets: {e}")
        st.info("Vérifie que les nouvelles tables SQL ont bien été créées dans PostgreSQL.")
    finally:
        db.close()


# =========================
# Admin - Form correction rejet
# =========================
def _rejected_product_form_ui(rejected_id: int | None):
    if rejected_id is None:
        st.error("Produit rejeté introuvable.")
        if st.button("⬅️ Retour à la liste des rejets"):
            st.session_state["admin_mode"] = "reject_list"
            st.session_state.pop("admin_rejected_id", None)
            st.rerun()
        return

    db = SessionLocal()
    try:
        rejected = (
            db.execute(
                select(RejectedProductReview).where(RejectedProductReview.rejected_id == int(rejected_id))
            )
            .scalars()
            .first()
        )

        if not rejected:
            st.error("Produit rejeté introuvable.")
            if st.button("⬅️ Retour à la liste des rejets"):
                st.session_state["admin_mode"] = "reject_list"
                st.session_state.pop("admin_rejected_id", None)
                st.rerun()
            return

        correction = _get_active_correction_for_code(db, rejected.code_produit)
        payload = rejected.raw_payload if isinstance(rejected.raw_payload, dict) else {}
        issues = rejected.quality_issues if isinstance(rejected.quality_issues, list) else []

        st.subheader(f"✏️ Correction manuelle — {rejected.code_produit}")
        st.caption(
            f"Nom: {rejected.product_name or 'N/A'} | "
            f"Marque: {rejected.brands or 'N/A'} | "
            f"Statut: {rejected.review_status}"
        )
        st.warning(f"Causes de rejet: {_format_issue_list(issues) or 'N/A'}")

        with st.expander("Voir les données brutes du produit"):
            st.json(payload)

        source_product_name = _payload_field_value(payload, "product_name", "product_name_en", "product_name_fr")
        source_brands = _payload_field_value(payload, "brands", "brands_en", "brands_fr")
        source_categories = _payload_field_value(payload, "categories", "categories_old", "categories_en", "categories_fr")
        source_categories_tags = _payload_field_value(payload, "categories_tags")
        source_primary_category = _payload_field_value(payload, "categorie_principale", "pnns_groups_2", "pnns_groups_1")
        source_ingredients = _payload_field_value(
            payload,
            "ingredients_text",
            "ingredients_text_en",
            "ingredients_text_fr",
            "ingredients_text_with_allergens",
        )

        with st.form("rejected_product_correction_form", clear_on_submit=False):
            corrected_by = st.text_input(
                "Corrigé par",
                value=(correction.corrected_by if correction and correction.corrected_by else ""),
            )
            st.markdown("**Colonnes produit corrigibles**")

            src_col, edit_col = st.columns(2)
            with src_col:
                st.text_input(
                    "Nom produit actuel",
                    value=source_product_name or rejected.product_name or "",
                    disabled=True,
                )
            with edit_col:
                product_name_manual = st.text_input(
                    "Nom produit corrigé",
                    value=_manual_or_source_value(
                        correction.product_name_manual if correction else None,
                        source_product_name or rejected.product_name or "",
                    ),
                )

            src_col, edit_col = st.columns(2)
            with src_col:
                st.text_input(
                    "Marque actuelle",
                    value=source_brands or rejected.brands or "",
                    disabled=True,
                )
            with edit_col:
                brands_manual = st.text_input(
                    "Marque corrigée",
                    value=_manual_or_source_value(
                        correction.brands_manual if correction else None,
                        source_brands or rejected.brands or "",
                    ),
                )

            src_col, edit_col = st.columns(2)
            with src_col:
                st.text_area(
                    "Catégories actuelles",
                    value=source_categories,
                    height=70,
                    disabled=True,
                )
            with edit_col:
                categories_manual = st.text_area(
                    "Catégories corrigées",
                    value=_manual_or_source_value(
                        correction.categories_manual if correction else None,
                        source_categories,
                    ),
                    height=70,
                    placeholder="teas, herbal teas",
                )

            src_col, edit_col = st.columns(2)
            with src_col:
                st.text_area(
                    "Tags catégories actuels",
                    value=source_categories_tags,
                    height=70,
                    disabled=True,
                )
            with edit_col:
                categories_tags_manual = st.text_area(
                    "Tags catégories corrigés",
                    value=_manual_or_source_value(
                        ", ".join(correction.categories_tags_manual)
                        if correction and correction.categories_tags_manual
                        else None,
                        source_categories_tags,
                    ),
                    placeholder="en:teas, en:herbal-teas",
                    height=70,
                )

            src_col, edit_col = st.columns(2)
            with src_col:
                st.text_input(
                    "Catégorie principale actuelle",
                    value=source_primary_category,
                    disabled=True,
                )
            with edit_col:
                categorie_principale_manual = st.text_input(
                    "Catégorie principale corrigée",
                    value=_manual_or_source_value(
                        correction.categorie_principale_manual if correction else None,
                        source_primary_category,
                    ),
                    placeholder="boisson",
                )

            src_col, edit_col = st.columns(2)
            with src_col:
                st.text_area(
                    "Ingrédients actuels",
                    value=source_ingredients,
                    height=120,
                    disabled=True,
                )
            with edit_col:
                ingredients_text_manual = st.text_area(
                    "Ingrédients corrigés",
                    value=_manual_or_source_value(
                        correction.ingredients_text_manual if correction else None,
                        source_ingredients,
                    ),
                    height=120,
                )
            commentaire = st.text_area(
                "Commentaire admin",
                value=(correction.commentaire if correction and correction.commentaire else ""),
                height=80,
            )
            correction_status = st.selectbox(
                "Statut de la correction",
                ["draft", "ready_for_pipeline", "archived"],
                index=["draft", "ready_for_pipeline", "archived"].index(
                    correction.correction_status
                    if correction and correction.correction_status in {"draft", "ready_for_pipeline", "archived"}
                    else "draft"
                ),
            )

            save = st.form_submit_button("Enregistrer la correction")

        c1, c2 = st.columns(2)
        with c1:
            ignore_clicked = st.button("Ignorer ce rejet", type="secondary")
        with c2:
            back_clicked = st.button("⬅️ Retour à la liste des rejets")

        if save:
            try:
                now = _utcnow()
                tags_manual = _split_csv(categories_tags_manual)

                if correction is None:
                    correction = ManualProductCorrection(
                        rejected_id=rejected.rejected_id,
                        code_produit=rejected.code_produit,
                        created_at=now,
                    )
                    db.add(correction)

                correction.rejected_id = rejected.rejected_id
                correction.code_produit = rejected.code_produit
                correction.product_name_manual = product_name_manual.strip() or None
                correction.brands_manual = brands_manual.strip() or None
                correction.categories_manual = categories_manual.strip() or None
                correction.categories_tags_manual = tags_manual or None
                correction.categorie_principale_manual = categorie_principale_manual.strip() or None
                correction.ingredients_text_manual = ingredients_text_manual.strip() or None
                correction.commentaire = commentaire.strip() or None
                correction.corrected_by = corrected_by.strip() or None
                correction.correction_status = correction_status
                correction.is_active = correction_status != "archived"
                correction.updated_at = now

                rejected.review_status = "corrected" if correction_status == "ready_for_pipeline" else "in_review"
                rejected.updated_at = now

                db.commit()
                st.session_state["admin_flash"] = {
                    "level": "success",
                    "message": f"Correction enregistrée pour le produit {rejected.code_produit}.",
                }
                st.session_state["admin_mode"] = "reject_list"
                st.session_state.pop("admin_rejected_id", None)
                st.rerun()
            except SQLAlchemyError as e:
                db.rollback()
                st.error(f"Erreur enregistrement correction: {e}")
            except Exception as e:
                db.rollback()
                st.error(f"Erreur inattendue enregistrement correction: {e}")

        if ignore_clicked:
            try:
                rejected.review_status = "ignored"
                rejected.updated_at = _utcnow()
                db.commit()
                st.success("Produit marqué comme ignoré.")
                st.session_state["admin_mode"] = "reject_list"
                st.session_state.pop("admin_rejected_id", None)
                st.rerun()
            except SQLAlchemyError as e:
                db.rollback()
                st.error(f"Erreur mise à jour statut: {e}")

        if back_clicked:
            st.session_state["admin_mode"] = "reject_list"
            st.session_state.pop("admin_rejected_id", None)
            st.rerun()

    except SQLAlchemyError as e:
        st.error(f"Erreur chargement correction: {e}")
        st.info("Vérifie que les nouvelles tables SQL ont bien été créées dans PostgreSQL.")
    finally:
        db.close()


# =========================
# Admin - Form Produit (avec marque/catégories/ingrédients)
# =========================
def _product_form_ui(is_edit: bool, code: str | None = None):
    db = SessionLocal()
    p = None

    try:
        code_clean = None

        if is_edit:
            code_clean = str(code).strip()

            if not code_clean:
                st.error("Code produit invalide.")
                if st.button("⬅️ Retour"):
                    st.session_state["admin_mode"] = "list"
                    st.session_state.pop("admin_code", None)
                    st.rerun()
                return

            p = db.query(Product).filter(Product.code_produit == code_clean).first()

            if not p:
                st.error("Produit introuvable.")
                if st.button("⬅️ Retour"):
                    st.session_state["admin_mode"] = "list"
                    st.session_state.pop("admin_code", None)
                    st.rerun()
                return

        all_categories = _get_all_categories(db)
        category_map = {c.categorie: c for c in all_categories}
        category_labels = list(category_map.keys())

        selected_categories_default = []
        if p:
            selected_categories_default = _get_selected_categories_for_product(
                db,
                str(p.code_produit)
            )

        st.subheader("✏️ Modifier un produit" if is_edit else "➕ Ajouter un produit")

        with st.form("product_form", clear_on_submit=False):
            code_val = st.text_input(
                "Code produit",
                value=(str(p.code_produit) if p else ""),
                disabled=is_edit,
            )

            name_val = st.text_input(
                "Nom produit",
                value=((p.nom_produit or "") if p else "")
            )

            grade_val = st.text_input(
                "Nutrition grade (A-E)",
                value=((p.nutrition_grade or "") if p else "")
            )

            nutri_score_val = st.text_input(
                "Nutriscore score (int)",
                value=(str(p.nutriscore_score) if p and p.nutriscore_score is not None else ""),
            )

            nova_val = st.text_input(
                "Nova group (int)",
                value=(str(p.nova_group) if p and p.nova_group is not None else ""),
            )

            url_val = st.text_input(
                "URL",
                value=((p.url or "") if p else "")
            )

            image_url_val = st.text_input(
                "Image URL",
                value=((p.image_url or "") if p else "")
            )

            marque_nom = st.text_input(
                "Marque",
                value=((p.brands or "") if p else "")
            )

            selected_categories_labels = st.multiselect(
                "Catégories",
                options=category_labels,
                default=selected_categories_default,
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

                code_clean = code_val.strip()

                if not is_edit:
                    exists = db.query(Product).filter(Product.code_produit == code_clean).first()
                    if exists:
                        st.error("Ce code produit existe déjà.")
                        return

                    p = Product(code_produit=code_clean)
                    db.add(p)

                p.nom_produit = name_val.strip()
                p.nutrition_grade = (grade_val.strip()[:1].upper() if grade_val.strip() else None)
                p.nutriscore_score = (int(nutri_score_val) if nutri_score_val.strip() else None)
                p.nova_group = (int(nova_val) if nova_val.strip() else None)
                p.url = (url_val.strip() or None)
                p.image_url = (image_url_val.strip() or None)

                m = _get_or_create_marque(db, marque_nom)
                p.id_marque = (m.id_marque if m else None)

                db.flush()

                cats = [category_map[label] for label in selected_categories_labels]
                ings = _get_or_create_ingredients(db, ingredients_txt)

                _replace_product_categories(db, str(p.code_produit), cats)
                _replace_product_ingredients(db, str(p.code_produit), ings)

                db.commit()
                st.success("✅ Enregistré.")
                st.session_state["admin_mode"] = "list"
                st.session_state.pop("admin_code", None)
                st.rerun()

            except (ValueError, SQLAlchemyError) as e:
                db.rollback()
                st.error(f"Erreur enregistrement: {e}")

            except Exception as e:
                db.rollback()
                st.error(f"Erreur inattendue enregistrement: {e}")

        if st.button("⬅️ Retour"):
            st.session_state["admin_mode"] = "list"
            st.session_state.pop("admin_code", None)
            st.rerun()

    finally:
        db.close()


# =========================
# Admin - Delete confirm
# =========================
def _delete_ui(code: str | None):
    st.subheader(f"🗑️ Supprimer produit {code}")

    code_clean = str(code).strip() if code is not None else ""

    if not code_clean:
        st.error("Code produit invalide.")
        if st.button("⬅️ Retour à la liste"):
            st.session_state["admin_mode"] = "list"
            st.session_state.pop("admin_code", None)
            st.rerun()
        return

    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.code_produit == code_clean).first()

        if not p:
            st.error("Produit introuvable.")
            st.session_state["admin_mode"] = "list"
            st.session_state.pop("admin_code", None)
            st.rerun()
            return

        st.warning("Cette action est irréversible.")

        c1, c2 = st.columns(2)

        with c1:
            if st.button("✅ Confirmer suppression"):
                try:
                    db.execute(
                        delete(produit_categorie).where(produit_categorie.c.code_produit == code_clean)
                    )

                    db.execute(
                        delete(produit_ingredient).where(produit_ingredient.c.code_produit == code_clean)
                    )

                    db.delete(p)
                    db.commit()

                    st.success("Supprimé ✅")
                    st.session_state["admin_mode"] = "list"
                    st.session_state.pop("admin_code", None)
                    st.rerun()

                except SQLAlchemyError as e:
                    db.rollback()
                    st.error(f"Erreur suppression: {e}")

                except Exception as e:
                    db.rollback()
                    st.error(f"Erreur inattendue suppression: {e}")

        with c2:
            if st.button("❌ Annuler"):
                st.session_state["admin_mode"] = "list"
                st.session_state.pop("admin_code", None)
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

    st.success("Connecte en admin")
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

    elif mode == "reject_list":
        _rejected_products_list_ui()

    elif mode == "reject_edit":
        _rejected_product_form_ui(rejected_id=st.session_state.get("admin_rejected_id"))

    else:
        st.session_state["admin_mode"] = "list"
        st.rerun()
