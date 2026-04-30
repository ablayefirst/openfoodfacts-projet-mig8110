"""Panel d'administration — schéma v3.

Changements :
- produit.id_produit (SERIAL PK), code_barre (TEXT UNIQUE)
- marque.nom_marque (anciennement brands)
- categorie.nom_categorie (anciennement categorie)
- Valeurs nutritionnelles dans produit (plus de table séparée)
- Suppression tables ingredient/produit_ingredient → ingredient_standardise/contient
- Allergènes via trace (pas de produit_allergene direct)
- Les tables RejectedProductReview / ManualProductCorrection sont inchangées

Corrections appliquées :
- CORRECTION point 7 : recherche produit étendue à la marque via join(Marque)
"""

import math
import os
from datetime import UTC, datetime

import streamlit as st
from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.exc import SQLAlchemyError

from db import SessionLocal
from models import (
    Categorie,
    Contient,
    IngredientStandardise,
    ManualProductCorrection,
    Marque,
    Product,
    RejectedProductReview,
    produit_categorie,
)


# ── Helpers ───────────────────────────────────────────────────────

def _split_csv(txt: str) -> list[str]:
    if not txt:
        return []
    return [p.strip() for p in txt.replace("|", ",").split(",") if p.strip()]


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def _get_or_create_marque(db, marque_nom: str | None) -> Marque | None:
    if not marque_nom or not marque_nom.strip():
        return None
    name = marque_nom.strip()
    obj = (
        db.execute(
            select(Marque)
            .where(func.lower(Marque.nom_marque) == name.lower())
            .order_by(Marque.id_marque.asc())
        ).scalars().first()
    )
    if obj:
        return obj
    obj = Marque(nom_marque=name)
    db.add(obj)
    db.flush()
    return obj


def _get_or_create_categories(db, categories_txt: str | None) -> list[Categorie]:
    items = _split_csv(categories_txt or "")
    out: list[Categorie] = []
    for c in items:
        obj = (
            db.execute(
                select(Categorie)
                .where(func.lower(Categorie.nom_categorie) == c.lower())
                .order_by(Categorie.id_categorie.asc())
            ).scalars().first()
        )
        if not obj:
            obj = Categorie(nom_categorie=c)
            db.add(obj)
            db.flush()
        out.append(obj)
    return out


def _get_all_categories(db) -> list[Categorie]:
    return db.execute(select(Categorie).order_by(Categorie.nom_categorie.asc())).scalars().all()


def _replace_product_categories(db, id_produit: int, categories: list[Categorie]) -> None:
    db.execute(delete(produit_categorie).where(produit_categorie.c.id_produit == id_produit))
    if categories:
        db.execute(
            insert(produit_categorie),
            [{"id_produit": id_produit, "id_categorie": c.id_categorie, "niveau": 1} for c in categories],
        )


def _get_selected_categories_for_product(db, id_produit: int) -> list[str]:
    rows = db.execute(
        select(Categorie.nom_categorie)
        .select_from(produit_categorie.join(Categorie, produit_categorie.c.id_categorie == Categorie.id_categorie))
        .where(produit_categorie.c.id_produit == id_produit)
        .order_by(Categorie.nom_categorie.asc())
    ).all()
    return [r[0] for r in rows]


def _get_ingredients_for_product(db, id_produit: int) -> str:
    """Retourne les ingrédients du produit sous forme de string séparée par virgule."""
    rows = db.execute(
        select(IngredientStandardise.nom_canonique)
        .select_from(
            Contient.__table__.join(
                IngredientStandardise.__table__,
                Contient.id_ingredient == IngredientStandardise.id_ingredient,
            )
        )
        .where(Contient.id_produit == id_produit)
        .order_by(Contient.ordre.asc())
    ).all()
    return ", ".join(r[0] for r in rows)


def _replace_product_ingredients(db, id_produit: int, ingredients_txt: str | None) -> None:
    """Remplace les ingrédients via la table contient + ingredient_standardise."""
    db.execute(delete(Contient.__table__).where(Contient.id_produit == id_produit))
    items = _split_csv(ingredients_txt or "")
    for ordre, nom in enumerate(items, start=1):
        ing = db.execute(
            select(IngredientStandardise)
            .where(func.lower(IngredientStandardise.nom_canonique) == nom.lower())
        ).scalars().first()
        if not ing:
            ing = IngredientStandardise(nom_canonique=nom.lower().strip())
            db.add(ing)
            db.flush()
        contient = Contient(
            id_produit=id_produit,
            id_ingredient=ing.id_ingredient,
            ordre=ordre,
            niveau=1,
        )
        db.add(contient)
    db.flush()


def _get_active_correction_for_code(db, code_produit: str) -> ManualProductCorrection | None:
    return (
        db.execute(
            select(ManualProductCorrection)
            .where(
                ManualProductCorrection.code_produit == code_produit,
                ManualProductCorrection.is_active.is_(True),
            )
            .order_by(ManualProductCorrection.updated_at.desc(), ManualProductCorrection.correction_id.desc())
        ).scalars().first()
    )


def _format_issue_list(issues) -> str:
    if isinstance(issues, list):
        return ", ".join(str(i) for i in issues if i)
    return str(issues) if issues else ""


def _payload_field_value(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            formatted = ", ".join(str(i) for i in value if i not in {None, ""})
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


# ── Auth ──────────────────────────────────────────────────────────

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
        for key in ["admin_ok", "admin_mode", "admin_id", "admin_rejected_id",
                    "admin_q", "admin_page", "reject_q", "reject_status", "admin_flash"]:
            st.session_state.pop(key, None)
        st.rerun()


def _show_admin_flash():
    flash = st.session_state.pop("admin_flash", None)
    if not flash:
        return
    level   = flash.get("level", "success")
    message = flash.get("message", "")
    if not message:
        return
    {"error": st.error, "warning": st.warning}.get(level, st.success)(message)


# ── Liste produits ────────────────────────────────────────────────

def _products_list_ui():
    st.subheader("📦 Admin - Produits")
    nav1, nav2 = st.columns(2)
    with nav1:
        st.button("📦 Produits", disabled=True, use_container_width=True)
    with nav2:
        if st.button("🛠️ Rejets à corriger", use_container_width=True):
            st.session_state["admin_mode"] = "reject_list"
            st.rerun()

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        q = st.text_input("Recherche (code / nom / marque)", value=st.session_state.get("admin_q", ""))
    with c2:
        per_page = st.selectbox("Par page", [10, 25, 50, 100], index=1)
    with c3:
        page = st.number_input("Page", min_value=1, value=int(st.session_state.get("admin_page", 1)), step=1)

    st.session_state["admin_q"]    = q
    st.session_state["admin_page"] = page

    db = SessionLocal()
    try:
        query_db = db.query(Product)
        qn = (q or "").strip()
        if qn:
            like = f"%{qn}%"
            if qn.isdigit():
                query_db = query_db.filter(
                    (Product.id_produit == int(qn)) | (Product.code_barre == qn)
                )
            else:
                # CORRECTION point 7 : ajout de la recherche sur la marque via join.
                # Avant : uniquement nom_produit et code_barre.
                # Après : nom_produit, code_barre ET nom_marque (ex: chercher "Nestlé").
                query_db = (
                    query_db
                    .outerjoin(Marque, Product.id_marque == Marque.id_marque)
                    .filter(
                        or_(
                            Product.nom_produit.ilike(like),
                            Product.code_barre.ilike(like),
                            Marque.nom_marque.ilike(like),
                        )
                    )
                )

        total       = query_db.count()
        total_pages = max(1, math.ceil(total / per_page))
        if page > total_pages:
            page = total_pages
            st.session_state["admin_page"] = page

        products = (
            query_db.order_by(Product.id_produit.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        st.caption(f"Total: **{total}** | Pages: **{total_pages}** | Page: **{page}**")
        st.divider()

        if st.button("➕ Ajouter un produit"):
            st.session_state["admin_mode"] = "new"
            st.session_state.pop("admin_id", None)
            st.rerun()

        st.divider()

        for p in products:
            nom_marque = p.marque.nom_marque if p.marque else "N/A"
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1:
                st.write(f"**{p.code_barre or p.id_produit}** — {p.nom_produit or ''}")
                st.caption(
                    f"NutriScore: {p.nutrition_grade or 'N/A'} | "
                    f"Nova: {p.nova_group or 'N/A'} | "
                    f"Marque: {nom_marque}"
                )
            with c2:
                if st.button("✏️ Modifier", key=f"edit_{p.id_produit}"):
                    st.session_state["admin_mode"] = "edit"
                    st.session_state["admin_id"]   = int(p.id_produit)
                    st.rerun()
            with c3:
                if st.button("🗑️ Supprimer", key=f"del_{p.id_produit}"):
                    st.session_state["admin_mode"] = "delete"
                    st.session_state["admin_id"]   = int(p.id_produit)
                    st.rerun()
    finally:
        db.close()


# ── Liste rejets ──────────────────────────────────────────────────

def _rejected_products_list_ui():
    st.subheader("🛠️ Produits rejetés à corriger")
    _show_admin_flash()
    nav1, nav2 = st.columns(2)
    with nav1:
        if st.button("📦 Produits", use_container_width=True):
            st.session_state["admin_mode"] = "list"
            st.rerun()
    with nav2:
        st.button("🛠️ Rejets à corriger", disabled=True, use_container_width=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        q = st.text_input("Recherche code / nom / marque", value=st.session_state.get("reject_q", ""))
    with c2:
        status_filter = st.selectbox(
            "Statut",
            ["all", "pending", "in_review", "corrected", "resolved", "ignored"],
            index=["all", "pending", "in_review", "corrected", "resolved", "ignored"].index(
                st.session_state.get("reject_status", "all")
            ),
        )
    st.session_state["reject_q"]      = q
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
            query_db.order_by(
                RejectedProductReview.created_at.desc(),
                RejectedProductReview.rejected_id.desc()
            ).limit(200).all()
        )

        st.caption(f"Résultats: **{len(rejected_products)}**")
        st.divider()

        if not rejected_products:
            st.info("Aucun produit rejeté à afficher.")
            return

        for rejected in rejected_products:
            correction = _get_active_correction_for_code(db, rejected.code_produit)
            c1, c2 = st.columns([4, 1])
            with c1:
                st.write(f"**{rejected.code_produit}** — {rejected.product_name or 'Sans nom'}")
                st.caption(
                    f"Marque: {rejected.brands or 'N/A'} | "
                    f"Issues: {_format_issue_list(rejected.quality_issues) or 'N/A'} | "
                    f"Statut: {rejected.review_status}"
                )
                if correction:
                    st.caption(
                        f"Correction active: {correction.correction_status} | "
                        f"Par: {correction.corrected_by or 'N/A'}"
                    )
            with c2:
                if st.button("✏️ Corriger", key=f"reject_edit_{rejected.rejected_id}"):
                    st.session_state["admin_mode"]         = "reject_edit"
                    st.session_state["admin_rejected_id"]  = int(rejected.rejected_id)
                    st.rerun()

    except SQLAlchemyError as e:
        st.error(f"Erreur chargement rejets: {e}")
        st.info("Vérifiez que les tables SQL ont bien été créées dans PostgreSQL.")
    finally:
        db.close()


# ── Formulaire correction rejet ───────────────────────────────────

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
        rejected = db.execute(
            select(RejectedProductReview).where(RejectedProductReview.rejected_id == int(rejected_id))
        ).scalars().first()

        if not rejected:
            st.error("Produit rejeté introuvable.")
            if st.button("⬅️ Retour"):
                st.session_state["admin_mode"] = "reject_list"
                st.rerun()
            return

        correction = _get_active_correction_for_code(db, rejected.code_produit)
        payload    = rejected.raw_payload if isinstance(rejected.raw_payload, dict) else {}
        issues     = rejected.quality_issues if isinstance(rejected.quality_issues, list) else []

        st.subheader(f"✏️ Correction manuelle — {rejected.code_produit}")
        st.caption(
            f"Nom: {rejected.product_name or 'N/A'} | "
            f"Marque: {rejected.brands or 'N/A'} | "
            f"Statut: {rejected.review_status}"
        )
        st.warning(f"Causes de rejet: {_format_issue_list(issues) or 'N/A'}")

        with st.expander("Voir les données brutes"):
            st.json(payload)

        source_product_name      = _payload_field_value(payload, "product_name", "product_name_en", "product_name_fr")
        source_brands            = _payload_field_value(payload, "brands", "brands_en", "brands_fr")
        source_categories        = _payload_field_value(payload, "categories", "categories_old", "categories_en", "categories_fr")
        source_categories_tags   = _payload_field_value(payload, "categories_tags")
        source_primary_category  = _payload_field_value(payload, "categorie_principale", "pnns_groups_2", "pnns_groups_1")
        source_ingredients       = _payload_field_value(payload, "ingredients_text", "ingredients_text_en", "ingredients_text_fr", "ingredients_text_with_allergens")

        with st.form("rejected_product_correction_form", clear_on_submit=False):
            corrected_by = st.text_input("Corrigé par", value=(correction.corrected_by if correction and correction.corrected_by else ""))
            st.markdown("**Colonnes produit corrigibles**")

            for label_src, src_val, label_edit, edit_key in [
                ("Nom produit actuel",              source_product_name or rejected.product_name or "",    "Nom produit corrigé",              "product_name_manual"),
                ("Marque actuelle",                 source_brands or rejected.brands or "",                "Marque corrigée",                  "brands_manual"),
                ("Catégorie principale actuelle",   source_primary_category,                              "Catégorie principale corrigée",    "categorie_principale_manual"),
            ]:
                sc, ec = st.columns(2)
                with sc:
                    st.text_input(label_src, value=src_val, disabled=True)
                with ec:
                    stored = getattr(correction, edit_key, None) if correction else None
                    globals()[edit_key] = st.text_input(label_edit, value=_manual_or_source_value(stored, src_val))

            sc, ec = st.columns(2)
            with sc:
                st.text_area("Catégories actuelles",    value=source_categories,      height=70, disabled=True)
            with ec:
                stored = correction.categories_manual if correction else None
                categories_manual = st.text_area("Catégories corrigées", value=_manual_or_source_value(stored, source_categories), height=70, placeholder="teas, herbal teas")

            sc, ec = st.columns(2)
            with sc:
                st.text_area("Tags catégories actuels", value=source_categories_tags, height=70, disabled=True)
            with ec:
                stored_tags = (", ".join(correction.categories_tags_manual) if correction and correction.categories_tags_manual else None)
                categories_tags_manual = st.text_area("Tags catégories corrigés", value=_manual_or_source_value(stored_tags, source_categories_tags), height=70, placeholder="en:teas, en:herbal-teas")

            sc, ec = st.columns(2)
            with sc:
                st.text_area("Ingrédients actuels",     value=source_ingredients,     height=120, disabled=True)
            with ec:
                stored_ing = correction.ingredients_text_manual if correction else None
                ingredients_text_manual = st.text_area("Ingrédients corrigés", value=_manual_or_source_value(stored_ing, source_ingredients), height=120)

            commentaire = st.text_area("Commentaire admin", value=(correction.commentaire if correction and correction.commentaire else ""), height=80)
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
                if correction is None:
                    correction = ManualProductCorrection(
                        rejected_id=rejected.rejected_id,
                        code_produit=rejected.code_produit,
                        created_at=now,
                    )
                    db.add(correction)

                correction.product_name_manual         = locals().get("product_name_manual", "").strip() or None
                correction.brands_manual               = locals().get("brands_manual", "").strip() or None
                correction.categories_manual           = categories_manual.strip() or None
                correction.categories_tags_manual      = _split_csv(categories_tags_manual) or None
                correction.categorie_principale_manual = locals().get("categorie_principale_manual", "").strip() or None
                correction.ingredients_text_manual     = ingredients_text_manual.strip() or None
                correction.commentaire                 = commentaire.strip() or None
                correction.corrected_by                = corrected_by.strip() or None
                correction.correction_status           = correction_status
                correction.is_active                   = correction_status != "archived"
                correction.updated_at                  = now

                rejected.review_status = "corrected" if correction_status == "ready_for_pipeline" else "in_review"
                rejected.updated_at    = now

                db.commit()
                st.session_state["admin_flash"] = {
                    "level": "success",
                    "message": f"Correction enregistrée pour {rejected.code_produit}.",
                }
                st.session_state["admin_mode"] = "reject_list"
                st.session_state.pop("admin_rejected_id", None)
                st.rerun()
            except (SQLAlchemyError, Exception) as e:
                db.rollback()
                st.error(f"Erreur enregistrement correction: {e}")

        if ignore_clicked:
            try:
                rejected.review_status = "ignored"
                rejected.updated_at    = _utcnow()
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
    finally:
        db.close()


# ── Formulaire produit ────────────────────────────────────────────

def _product_form_ui(is_edit: bool, id_produit: int | None = None):
    db = SessionLocal()
    p  = None

    try:
        if is_edit:
            if id_produit is None:
                st.error("Identifiant produit invalide.")
                if st.button("⬅️ Retour"):
                    st.session_state["admin_mode"] = "list"
                    st.rerun()
                return
            p = db.query(Product).filter(Product.id_produit == id_produit).first()
            if not p:
                st.error("Produit introuvable.")
                if st.button("⬅️ Retour"):
                    st.session_state["admin_mode"] = "list"
                    st.rerun()
                return

        all_categories  = _get_all_categories(db)
        category_map    = {c.nom_categorie: c for c in all_categories}
        category_labels = list(category_map.keys())

        selected_cats_default = []
        ingredients_default   = ""
        if p:
            selected_cats_default = _get_selected_categories_for_product(db, p.id_produit)
            ingredients_default   = _get_ingredients_for_product(db, p.id_produit)

        st.subheader("✏️ Modifier un produit" if is_edit else "➕ Ajouter un produit")

        with st.form("product_form", clear_on_submit=False):
            code_val = st.text_input("Code-barre (EAN)", value=(p.code_barre or "" if p else ""))
            name_val = st.text_input("Nom produit",      value=(p.nom_produit or "" if p else ""))

            grade_val       = st.text_input("Nutrition grade (A-E)",   value=(p.nutrition_grade or "" if p else ""))
            nutri_score_val = st.text_input("Nutriscore score (int)",   value=(str(p.nutriscore_score) if p and p.nutriscore_score is not None else ""))
            nova_val        = st.text_input("Nova group (int)",         value=(str(p.nova_group) if p and p.nova_group is not None else ""))
            url_val         = st.text_input("URL",                      value=(p.url or "" if p else ""))
            image_url_val   = st.text_input("Image URL",                value=(p.image_url or "" if p else ""))
            marque_nom      = st.text_input("Marque",                   value=(p.marque.nom_marque if p and p.marque else ""))
            cat_principale  = st.text_input("Catégorie principale",     value=(p.categorie_principale or "" if p else ""))

            selected_cats_labels = st.multiselect("Catégories détaillées", options=category_labels, default=selected_cats_default)
            ingredients_txt      = st.text_area("Ingrédients (séparés par , ou |)", value=ingredients_default, height=80)

            ok = st.form_submit_button("Enregistrer")

        if ok:
            try:
                if not name_val.strip():
                    st.error("Nom produit obligatoire.")
                    return

                if not is_edit:
                    p = Product(code_barre=code_val.strip() or None)
                    db.add(p)

                p.nom_produit          = name_val.strip()
                p.code_barre           = code_val.strip() or None
                p.nutrition_grade      = grade_val.strip()[:1].upper() if grade_val.strip() else None
                p.nutriscore_score     = int(nutri_score_val) if nutri_score_val.strip() else None
                p.nova_group           = int(nova_val)        if nova_val.strip()        else None
                p.url                  = url_val.strip()      or None
                p.image_url            = image_url_val.strip() or None
                p.categorie_principale = cat_principale.strip() or None

                m           = _get_or_create_marque(db, marque_nom)
                p.id_marque = m.id_marque if m else None

                db.flush()

                cats = [category_map[label] for label in selected_cats_labels]
                _replace_product_categories(db, p.id_produit, cats)
                _replace_product_ingredients(db, p.id_produit, ingredients_txt)

                db.commit()
                st.success("✅ Enregistré.")
                st.session_state["admin_mode"] = "list"
                st.session_state.pop("admin_id", None)
                st.rerun()

            except (ValueError, SQLAlchemyError, Exception) as e:
                db.rollback()
                st.error(f"Erreur enregistrement: {e}")

        if st.button("⬅️ Retour"):
            st.session_state["admin_mode"] = "list"
            st.session_state.pop("admin_id", None)
            st.rerun()

    finally:
        db.close()


# ── Suppression ───────────────────────────────────────────────────

def _delete_ui(id_produit: int | None):
    st.subheader(f"🗑️ Supprimer produit #{id_produit}")

    if id_produit is None:
        st.error("Identifiant produit invalide.")
        if st.button("⬅️ Retour à la liste"):
            st.session_state["admin_mode"] = "list"
            st.rerun()
        return

    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.id_produit == id_produit).first()
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
                    db.delete(p)
                    db.commit()
                    st.success("Supprimé ✅")
                    st.session_state["admin_mode"] = "list"
                    st.session_state.pop("admin_id", None)
                    st.rerun()
                except (SQLAlchemyError, Exception) as e:
                    db.rollback()
                    st.error(f"Erreur suppression: {e}")

        with c2:
            if st.button("❌ Annuler"):
                st.session_state["admin_mode"] = "list"
                st.session_state.pop("admin_id", None)
                st.rerun()

    finally:
        db.close()


# ── Entry point ───────────────────────────────────────────────────

def run_admin():
    if not st.session_state.get("admin_ok"):
        _login_ui()
        return

    st.success("Connecté en admin")
    _logout_ui()

    mode = st.session_state.get("admin_mode", "list")

    if mode == "list":
        _products_list_ui()
    elif mode == "new":
        _product_form_ui(is_edit=False)
    elif mode == "edit":
        _product_form_ui(is_edit=True, id_produit=st.session_state.get("admin_id"))
    elif mode == "delete":
        _delete_ui(id_produit=st.session_state.get("admin_id"))
    elif mode == "reject_list":
        _rejected_products_list_ui()
    elif mode == "reject_edit":
        _rejected_product_form_ui(rejected_id=st.session_state.get("admin_rejected_id"))
    else:
        st.session_state["admin_mode"] = "list"
        st.rerun()
