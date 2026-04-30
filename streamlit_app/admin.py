import os
import math
import re
from datetime import datetime, UTC
import streamlit as st

from sqlalchemy import or_, cast, String, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, delete, insert, func

from db import SessionLocal
from models import (
    Product,
    Marque,
    Categorie,
    Ingredient,
    ValeursNutritionnelles,
    RejectedProductReview,
    ProductCategorySuggestion,
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


def _get_nutrition_for_product(db, code_produit: str) -> ValeursNutritionnelles | None:
    return (
        db.execute(
            select(ValeursNutritionnelles)
            .where(ValeursNutritionnelles.code_produit == code_produit)
        )
        .scalars()
        .first()
    )


def _upsert_product_nutrition(db, code_produit: str, nutrient_values: dict[str, str]) -> None:
    nutrition = _get_nutrition_for_product(db, code_produit)
    parsed_values = {
        key: _parse_optional_float(value)
        for key, value in nutrient_values.items()
    }
    if not any(value is not None for value in parsed_values.values()):
        if nutrition is not None:
            db.delete(nutrition)
        return

    if nutrition is None:
        nutrition = ValeursNutritionnelles(code_produit=code_produit)
        db.add(nutrition)

    for key, value in parsed_values.items():
        setattr(nutrition, key, value)


def _build_manual_product_payload(
    *,
    code: str,
    name: str,
    brand: str,
    quantity: str,
    categories: list[str],
    ingredients: str,
    grade: str,
    nutri_score,
    nova,
    url: str,
    image_url: str,
    nutrient_values: dict[str, str],
) -> dict:
    payload = {
        "code": code,
        "product_name": name.strip(),
        "brands": brand.strip() or None,
        "quantity": quantity.strip() or None,
        "categories": ", ".join(categories),
        "categories_tags": [_tag_label_to_tag(category) for category in categories if _tag_label_to_tag(category)],
        "categorie_principale": categories[0].strip().lower() if categories else None,
        "ingredients_text": ingredients.strip() or None,
        "nutriscore_grade": grade.strip().lower()[:1] or None,
        "nutriscore_score": nutri_score,
        "nova_group": nova,
        "url": url.strip() or None,
        "image_url": image_url.strip() or None,
        "_manual_review": {
            "reviewed_at": _utcnow().isoformat(),
            "source": "streamlit_admin_new_product",
        },
    }
    nutriments = {}
    nutrient_payload_keys = {
        "energy_kcal_100g": ("energy-kcal_100g", "energy_kcal_100g"),
        "fat_100g": ("fat_100g",),
        "saturated_fat_100g": ("saturated-fat_100g", "saturated_fat_100g"),
        "carbohydrates_100g": ("carbohydrates_100g",),
        "sugars_100g": ("sugars_100g",),
        "fiber_100g": ("fiber_100g",),
        "proteins_100g": ("proteins_100g",),
        "salt_100g": ("salt_100g",),
    }
    for nutrient_key, payload_keys in nutrient_payload_keys.items():
        value = _parse_optional_float(nutrient_values.get(nutrient_key, ""))
        payload[nutrient_key] = value
        for payload_key in payload_keys:
            nutriments[payload_key] = value
    payload["nutriments"] = nutriments
    return payload


def _upsert_admin_product_pipeline_submission(
    db,
    *,
    code: str,
    name: str,
    brand: str,
    corrected_payload: dict,
    source_task: str,
    quality_issues: list[str] | None = None,
) -> RejectedProductReview:
    existing = (
        db.execute(
            select(RejectedProductReview)
            .where(
                RejectedProductReview.code_produit == code,
                RejectedProductReview.source_task == source_task,
                RejectedProductReview.review_status.in_(["pending", "suggested", "validated", "needs_review"]),
            )
            .order_by(RejectedProductReview.rejected_id.desc())
        )
        .scalars()
        .first()
    )
    now = _utcnow()
    if existing is None:
        existing = RejectedProductReview(
            code_produit=code,
            created_at=now,
            source_task=source_task,
            import_type="manual",
            raw_payload=corrected_payload,
            quality_issues=quality_issues or [],
        )
        db.add(existing)

    existing.product_name = name.strip()
    existing.brands = brand.strip() or None
    existing.raw_payload = corrected_payload
    existing.corrected_payload = corrected_payload
    existing.quality_issues = quality_issues or []
    existing.review_status = "validated"
    existing.updated_at = now
    return existing


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


def _get_active_suggestion_for_code(db, code_produit: str) -> ProductCategorySuggestion | None:
    return (
        db.execute(
            select(ProductCategorySuggestion)
            .where(
                ProductCategorySuggestion.code_produit == code_produit,
            )
            .order_by(ProductCategorySuggestion.updated_at.desc(), ProductCategorySuggestion.suggestion_id.desc())
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


def _humanize_review_status(status: str | None) -> str:
    mapping = {
        "pending": "A corriger",
        "suggested": "Suggestion disponible",
        "validated": "Correction validée",
        "resolved": "Validé par le pipeline",
        "ignored": "Ignoré",
        "needs_review": "A revoir",
    }
    if not status:
        return "N/A"
    return mapping.get(status, status)


def _humanize_suggestion_status(status: str | None) -> str:
    mapping = {
        "suggested": "Suggestion disponible",
        "validated": "Validée",
        "rejected": "Refusée",
        "needs_review": "A revoir",
        "applied": "Appliquée par le pipeline",
    }
    if not status:
        return "N/A"
    return mapping.get(status, status)


def _humanize_admin_source(source_task: str | None) -> str:
    mapping = {
        "streamlit_manual_add": "Ajout admin",
        "streamlit_product_edit": "Modification admin",
        "first_clean_from_bronze": "Correction rejet",
        "second_clean_from_bad": "Correction rejet",
    }
    if not source_task:
        return "N/A"
    return mapping.get(source_task, source_task)


def _pipeline_status_label(review: RejectedProductReview | None) -> str:
    if review is None:
        return "A jour"
    if review.review_status == "validated":
        return "En attente pipeline"
    if review.review_status == "resolved":
        return "Applique par pipeline"
    if review.review_status == "needs_review":
        return "A revoir"
    if review.review_status == "ignored":
        return "Ignore"
    return _humanize_review_status(review.review_status)


def _latest_pipeline_reviews_for_codes(db, codes: list[str]) -> dict[str, RejectedProductReview]:
    clean_codes = [str(code).strip() for code in codes if str(code).strip()]
    if not clean_codes:
        return {}

    rows = (
        db.execute(
            select(RejectedProductReview)
            .where(
                RejectedProductReview.code_produit.in_(clean_codes),
                RejectedProductReview.corrected_payload.is_not(None),
            )
            .order_by(
                RejectedProductReview.code_produit.asc(),
                RejectedProductReview.updated_at.desc(),
                RejectedProductReview.rejected_id.desc(),
            )
        )
        .scalars()
        .all()
    )
    latest: dict[str, RejectedProductReview] = {}
    for review in rows:
        code = str(review.code_produit)
        if code not in latest:
            latest[code] = review
    return latest


def _product_correction_history(db, code: str, limit: int = 5) -> list[RejectedProductReview]:
    code_clean = str(code or "").strip()
    if not code_clean:
        return []
    return (
        db.execute(
            select(RejectedProductReview)
            .where(
                RejectedProductReview.code_produit == code_clean,
                RejectedProductReview.corrected_payload.is_not(None),
            )
            .order_by(RejectedProductReview.updated_at.desc(), RejectedProductReview.rejected_id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def _payload_field_value(payload: dict, *keys: str) -> str:
    for key in keys:
        value = _payload_get(payload, key)
        if value is None:
            continue
        if isinstance(value, list):
            formatted = ", ".join(str(item) for item in value if item not in {None, ""})
            if _is_filled(formatted):
                return formatted
            continue
        text = str(value).strip()
        if _is_filled(text):
            return text
    return ""


def _manual_or_source_value(manual_value, source_value: str) -> str:
    if manual_value is None:
        return source_value
    text = str(manual_value).strip()
    return text if text else source_value


def _ensure_rejected_review_schema(db) -> None:
    """Keep older local databases compatible with the enhanced review screen."""
    db.execute(text("ALTER TABLE rejected_products_review ADD COLUMN IF NOT EXISTS corrected_payload JSONB"))
    db.commit()


def _is_filled(value) -> bool:
    if value is None:
        return False
    if isinstance(value, list | tuple | set):
        return any(_is_filled(item) for item in value)
    if isinstance(value, dict):
        return bool(value)
    text_value = str(value).strip()
    normalized = text_value.lower()
    empty_tokens = {
        "nan",
        "none",
        "null",
        "unknown",
        "undefined",
        "not-applicable",
        "not applicable",
        "n/a",
        "[]",
        "{}",
        "en:null",
        "en:unknown",
        "en:undefined",
    }
    return bool(text_value) and normalized not in empty_tokens


def _payload_first(payload: dict, *keys: str):
    for key in keys:
        value = _payload_get(payload, key)
        if _is_filled(value):
            return value
    return None


def _payload_get(payload: dict, key: str):
    if key in payload:
        return payload.get(key)

    current = payload
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current.get(part)
    return current


def _payload_text(payload: dict, *keys: str) -> str:
    value = _payload_first(payload, *keys)
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if _is_filled(item))
    text_value = str(value).strip()
    return text_value if _is_filled(text_value) else ""


def _payload_number(payload: dict, *keys: str):
    value = _payload_first(payload, *keys)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _value_from_sources(*values) -> str:
    for value in values:
        if _is_filled(value):
            if isinstance(value, list):
                return ", ".join(str(item) for item in value if _is_filled(item))
            return str(value).strip()
    return ""


def _tag_label_to_tag(label: str) -> str:
    clean_label = str(label or "").strip().lower()
    if not clean_label:
        return ""
    if clean_label.startswith("en:"):
        return clean_label
    return "en:" + re.sub(r"[^a-z0-9]+", "-", clean_label).strip("-")


def _nutrient_number(payload: dict, top_key: str, aliases: tuple[str, ...]):
    value = _payload_number(payload, top_key)
    if value is not None:
        return value

    nutriments = payload.get("nutriments")
    if not isinstance(nutriments, dict):
        return None

    for alias in aliases:
        value = _payload_number(nutriments, alias)
        if value is not None:
            return value
    return None


def _parse_optional_float(value: str):
    text_value = str(value or "").strip()
    if not text_value:
        return None
    return float(text_value.replace(",", "."))


def _parse_optional_int(value: str):
    text_value = str(value or "").strip()
    if not text_value:
        return None
    return int(float(text_value.replace(",", ".")))


def _format_optional_number(value) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _format_datetime(value) -> str:
    if value is None:
        return "N/A"
    return value.strftime("%Y-%m-%d %H:%M") if hasattr(value, "strftime") else str(value)


def _field_hint(text: str) -> None:
    st.caption(f"Indice: {text}")


_CORE_NUTRIENT_FIELDS = [
    ("energy_kcal_100g", "Énergie", ("energy_kcal_100g", "energy-kcal_100g", "energy_100g", "energy-kj_100g")),
    ("fat_100g", "Matières grasses", ("fat_100g",)),
    ("saturated_fat_100g", "Graisses saturées", ("saturated_fat_100g", "saturated-fat_100g")),
    ("carbohydrates_100g", "Glucides", ("carbohydrates_100g",)),
    ("sugars_100g", "Sucres", ("sugars_100g",)),
    ("fiber_100g", "Fibres", ("fiber_100g",)),
    ("proteins_100g", "Protéines", ("proteins_100g",)),
    ("salt_100g", "Sel", ("salt_100g", "sodium_100g")),
]

_PRODUCT_IMAGE_KEYS = (
    "image_url",
    "image_front_url",
    "image_small_url",
    "image_front_small_url",
    "image_thumb_url",
    "image_front_thumb_url",
)

_NUTRITION_IMAGE_KEYS = (
    "image_nutrition_url",
    "image_nutrition_small_url",
    "image_nutrition_thumb_url",
)


def _selected_image_url(payload: dict, image_type: str) -> str:
    selected_images = payload.get("selected_images")
    if not isinstance(selected_images, dict):
        return ""

    image_group = selected_images.get(image_type)
    if not isinstance(image_group, dict):
        return ""

    for size in ("display", "small", "thumb"):
        candidates = image_group.get(size)
        if not isinstance(candidates, dict):
            continue
        for lang in ("en", "fr", "front", "nutrition"):
            value = candidates.get(lang)
            if _is_filled(value):
                return str(value).strip()
        for value in candidates.values():
            if _is_filled(value):
                return str(value).strip()

    return ""


def _payload_image_url(payload: dict, image_type: str = "product") -> str:
    keys = _NUTRITION_IMAGE_KEYS if image_type == "nutrition" else _PRODUCT_IMAGE_KEYS
    direct_value = _payload_text(payload, *keys)
    if direct_value:
        return direct_value
    return _selected_image_url(payload, "nutrition" if image_type == "nutrition" else "front")


def _openfoodfacts_product_url(code: str | None) -> str:
    code_clean = str(code or "").strip()
    return f"https://world.openfoodfacts.org/product/{code_clean}" if code_clean else ""


def _build_corrected_payload(
    *,
    rejected: RejectedProductReview,
    payload: dict,
    product_name: str,
    brands: str,
    quantity: str,
    categories: str,
    categories_tags: str,
    primary_category: str,
    ingredients_text: str,
    allergens_tags: str,
    labels_tags: str,
    nutrition_grade: str,
    nutriscore_score: str,
    nova_group: str,
    image_url: str,
    image_nutrition_url: str,
    nutrient_values: dict[str, str],
) -> dict:
    corrected = dict(payload)
    corrected["code"] = rejected.code_produit
    corrected["product_name"] = product_name.strip()
    corrected["brands"] = brands.strip() or None
    corrected["quantity"] = quantity.strip() or None
    corrected["categories"] = categories.strip()
    corrected["categories_tags"] = _split_csv(categories_tags)
    corrected["categorie_principale"] = primary_category.strip() or None
    corrected["ingredients_text"] = ingredients_text.strip() or None
    corrected["allergens_tags"] = _split_csv(allergens_tags)
    corrected["labels_tags"] = _split_csv(labels_tags)
    corrected["nutriscore_grade"] = nutrition_grade.strip().lower()[:1] or None
    corrected["nutriscore_score"] = _parse_optional_int(nutriscore_score)
    corrected["nova_group"] = _parse_optional_int(nova_group)
    corrected["image_url"] = image_url.strip() or None
    corrected["image_nutrition_url"] = image_nutrition_url.strip() or None
    corrected["_manual_review"] = {
        "rejected_id": rejected.rejected_id,
        "reviewed_at": _utcnow().isoformat(),
        "source": "streamlit_admin",
    }

    for nutrient_key, _, _ in _CORE_NUTRIENT_FIELDS:
        corrected[nutrient_key] = _parse_optional_float(nutrient_values.get(nutrient_key, ""))

    nutriments = corrected.get("nutriments")
    if not isinstance(nutriments, dict):
        nutriments = {}
    nutrient_payload_keys = {
        "energy_kcal_100g": ("energy-kcal_100g", "energy_kcal_100g"),
        "fat_100g": ("fat_100g",),
        "saturated_fat_100g": ("saturated-fat_100g", "saturated_fat_100g"),
        "carbohydrates_100g": ("carbohydrates_100g",),
        "sugars_100g": ("sugars_100g",),
        "fiber_100g": ("fiber_100g",),
        "proteins_100g": ("proteins_100g",),
        "salt_100g": ("salt_100g",),
    }
    for nutrient_key, payload_keys in nutrient_payload_keys.items():
        value = corrected.get(nutrient_key)
        for payload_key in payload_keys:
            nutriments[payload_key] = value
    corrected["nutriments"] = nutriments

    return corrected


def _completion_report(payload: dict, min_core_nutrients: int | None = None) -> dict:
    min_core_nutrients = min_core_nutrients or int(os.getenv("OPENFOOD_MIN_CORE_NUTRIENTS", "2"))
    nutrient_count = _corrected_nutrient_count(payload)
    checks = [
        ("Code-barres", _is_filled(_payload_first(payload, "code", "code_produit"))),
        ("Nom produit", _is_filled(_payload_first(payload, "product_name", "product_name_en", "product_name_fr"))),
        ("Marque", _is_filled(_payload_first(payload, "brands", "brands_en", "brands_fr"))),
        ("Catégorie", _is_filled(_payload_first(payload, "categories", "categories_tags", "categorie_principale"))),
        ("Ingrédients", _is_filled(_payload_first(payload, "ingredients_text", "ingredients_text_en", "ingredients_text_fr"))),
        (f"Nutrition ({min_core_nutrients}+ champs)", nutrient_count >= min_core_nutrients),
        ("Image", bool(_payload_image_url(payload) or _payload_image_url(payload, "nutrition"))),
    ]
    done = sum(1 for _, ok in checks if ok)
    total = len(checks)
    return {
        "done": done,
        "total": total,
        "percent": int(round((done / total) * 100)) if total else 0,
        "missing": [label for label, ok in checks if not ok],
        "nutrient_count": nutrient_count,
    }


def _render_pipeline_preview(payload: dict | None, error: str | None = None) -> None:
    st.markdown("**Aperçu pipeline**")
    if error:
        st.warning(f"Non valide pour le pipeline: {error}")
        return
    if payload is None:
        st.warning("Aperçu indisponible.")
        return

    issues = _validate_corrected_payload(payload)
    completion = _completion_report(payload)
    expected_grade = _grade_from_score(_payload_text(payload, "nutriscore_score"))

    c1, c2, c3 = st.columns(3)
    c1.metric("Complétude", f"{completion['percent']}%")
    c2.metric("Nutriments", completion["nutrient_count"])
    c3.metric("NutriScore attendu", expected_grade.upper() if expected_grade else "N/A")

    if issues:
        st.warning("Non valide pour le pipeline.")
        st.caption("Problèmes: " + ", ".join(_humanize_contract_issue(issue) for issue in issues))
    else:
        st.success("Valide pour le pipeline.")

    if completion["missing"]:
        st.caption("Champs incomplets: " + ", ".join(completion["missing"]))


def _corrected_nutrient_count(payload: dict) -> int:
    count = 0
    for top_key, _, aliases in _CORE_NUTRIENT_FIELDS:
        value = _nutrient_number(payload, top_key, aliases)
        if value is not None:
            count += 1
    return count


def _score_matches_grade(grade: str | None, score: int | None) -> bool:
    if not grade and score is None:
        return True
    if not grade or score is None:
        return False
    grade_value = grade.strip().lower()[:1]
    ranges = {
        "a": (-15, -1),
        "b": (0, 2),
        "c": (3, 10),
        "d": (11, 18),
        "e": (19, 40),
    }
    if grade_value not in ranges:
        return False
    low, high = ranges[grade_value]
    return low <= score <= high


def _grade_from_score(score_value: str | int | float | None) -> str:
    try:
        score = _parse_optional_int(str(score_value or ""))
    except ValueError:
        return ""
    if score is None:
        return ""
    if score <= -1:
        return "a"
    if score <= 2:
        return "b"
    if score <= 10:
        return "c"
    if score <= 18:
        return "d"
    return "e"


def _normalize_grade_with_score(grade: str, score_value: str) -> str:
    expected_grade = _grade_from_score(score_value)
    if expected_grade:
        return expected_grade
    return str(grade or "").strip().lower()[:1]


def _quantity_looks_standardized(quantity: str | None) -> bool:
    text_value = str(quantity or "").strip()
    if not text_value:
        return True
    return bool(re.match(r"^\d+(?:[.,]\d+)?\s*(g|kg|ml|l|cl|oz|lb)\b", text_value.lower()))


def _url_looks_valid(value: str | None) -> bool:
    text_value = str(value or "").strip()
    if not text_value:
        return True
    return text_value.startswith(("http://", "https://"))


def _validate_corrected_payload(payload: dict) -> list[str]:
    issues: list[str] = []

    if not _is_filled(_payload_first(payload, "code")):
        issues.append("missing_code")
    if not _is_filled(_payload_first(payload, "product_name")):
        issues.append("missing_product_name")
    if not _is_filled(_payload_first(payload, "categories")):
        issues.append("missing_categories")
    if not _is_filled(_payload_first(payload, "categorie_principale")):
        issues.append("missing_categorie_principale")
    if not _quantity_looks_standardized(_payload_text(payload, "quantity")):
        issues.append("quantity_not_standardized")

    try:
        score = _parse_optional_int(_payload_text(payload, "nutriscore_score"))
    except ValueError:
        score = None
        issues.append("nutriscore_inconsistent")
    grade = _payload_text(payload, "nutriscore_grade")
    if "nutriscore_inconsistent" not in issues and not _score_matches_grade(grade, score):
        issues.append("nutriscore_inconsistent")

    return issues


def _humanize_contract_issue(issue: str) -> str:
    labels = {
        "missing_code": "Code-barres manquant",
        "missing_product_name": "Nom produit manquant",
        "missing_categories": "Catégorie manquante",
        "missing_categorie_principale": "Catégorie principale manquante",
        "quantity_not_standardized": "Quantité non standardisée",
        "nutriscore_inconsistent": "NutriScore incohérent",
    }
    return labels.get(issue, issue)


def _issue_list_contains(issues, target: str) -> bool:
    if isinstance(issues, list):
        return target in {str(issue) for issue in issues}
    if isinstance(issues, str):
        return target == issues or target in {part.strip() for part in issues.split(",")}
    return False


def _suggestion_tags(suggestion: ProductCategorySuggestion) -> list[str]:
    tags = suggestion.suggested_categories_tags
    if isinstance(tags, list):
        clean_tags = [str(tag).strip() for tag in tags if _is_filled(tag)]
        if clean_tags:
            return clean_tags

    suggested_categories = suggestion.suggested_categories or ""
    first_category = suggested_categories.split(",")[0].strip()
    tag = _tag_label_to_tag(first_category)
    return [tag] if tag else []


def _build_batch_corrected_payload(
    rejected: RejectedProductReview,
    suggestion: ProductCategorySuggestion,
) -> dict:
    payload = rejected.raw_payload if isinstance(rejected.raw_payload, dict) else {}
    corrected = dict(payload)

    suggested_categories = _payload_text(
        {"value": suggestion.suggested_categories},
        "value",
    )
    suggested_tags = _suggestion_tags(suggestion)
    suggested_primary = _value_from_sources(
        suggestion.suggested_categorie_principale,
        suggested_categories.split(",")[0].strip().lower() if suggested_categories else "",
    )

    corrected["code"] = rejected.code_produit
    corrected["product_name"] = _value_from_sources(
        _payload_text(corrected, "product_name", "product_name_en", "product_name_fr"),
        rejected.product_name,
    )
    corrected["brands"] = _value_from_sources(
        _payload_text(corrected, "brands", "brands_en", "brands_fr"),
        rejected.brands,
    ) or None
    corrected["categories"] = suggested_categories
    corrected["categories_tags"] = suggested_tags
    corrected["categorie_principale"] = suggested_primary or None

    score_value = _payload_text(corrected, "nutriscore_score")
    grade_value = _payload_text(corrected, "nutriscore_grade", "nutrition_grade_fr", "nutrition_grade")
    corrected["nutriscore_grade"] = _normalize_grade_with_score(grade_value, score_value) or None
    try:
        corrected["nutriscore_score"] = _parse_optional_int(score_value)
    except ValueError:
        corrected["nutriscore_score"] = None

    corrected["_manual_review"] = {
        "rejected_id": rejected.rejected_id,
        "reviewed_at": _utcnow().isoformat(),
        "source": "streamlit_admin_batch",
    }
    return corrected


def _get_batch_validation_candidates(
    db,
    confidence_threshold: float,
    limit: int = 100,
) -> list[tuple[RejectedProductReview, ProductCategorySuggestion, dict]]:
    rows = (
        db.execute(
            select(RejectedProductReview, ProductCategorySuggestion)
            .join(
                ProductCategorySuggestion,
                ProductCategorySuggestion.rejected_id == RejectedProductReview.rejected_id,
            )
            .where(
                RejectedProductReview.review_status.in_(["pending", "suggested", "needs_review"]),
                ProductCategorySuggestion.decision_status == "suggested",
                ProductCategorySuggestion.suggestion_confidence >= confidence_threshold,
            )
            .order_by(
                ProductCategorySuggestion.suggestion_confidence.desc(),
                RejectedProductReview.created_at.asc(),
            )
            .limit(limit * 3)
        )
        .all()
    )

    candidates: list[tuple[RejectedProductReview, ProductCategorySuggestion, dict]] = []
    for rejected, suggestion in rows:
        if not _issue_list_contains(rejected.quality_issues, "missing_categories"):
            continue
        if not _is_filled(suggestion.suggested_categories):
            continue

        corrected_payload = _build_batch_corrected_payload(rejected, suggestion)
        if _validate_corrected_payload(corrected_payload):
            continue

        candidates.append((rejected, suggestion, corrected_payload))
        if len(candidates) >= limit:
            break

    return candidates


def _batch_validation_diagnostics(db, confidence_threshold: float) -> dict[str, int]:
    rows = (
        db.execute(
            select(RejectedProductReview, ProductCategorySuggestion)
            .join(
                ProductCategorySuggestion,
                ProductCategorySuggestion.rejected_id == RejectedProductReview.rejected_id,
            )
            .where(ProductCategorySuggestion.suggestion_confidence >= confidence_threshold)
        )
        .all()
    )

    diagnostics = {
        "suggestions_above_threshold": len(rows),
        "not_actionable_status": 0,
        "already_decided": 0,
        "not_missing_categories": 0,
        "empty_suggestion": 0,
        "failed_validation": 0,
        "eligible": 0,
    }
    actionable_statuses = {"pending", "suggested", "needs_review"}

    for rejected, suggestion in rows:
        if rejected.review_status not in actionable_statuses:
            diagnostics["not_actionable_status"] += 1
            continue
        if suggestion.decision_status != "suggested":
            diagnostics["already_decided"] += 1
            continue
        if not _issue_list_contains(rejected.quality_issues, "missing_categories"):
            diagnostics["not_missing_categories"] += 1
            continue
        if not _is_filled(suggestion.suggested_categories):
            diagnostics["empty_suggestion"] += 1
            continue
        if _validate_corrected_payload(_build_batch_corrected_payload(rejected, suggestion)):
            diagnostics["failed_validation"] += 1
            continue
        diagnostics["eligible"] += 1

    return diagnostics


def _render_rejection_quality_analysis(db) -> None:
    with st.expander("Analyse qualité des rejets"):
        status_rows = db.execute(
            select(RejectedProductReview.review_status, func.count())
            .group_by(RejectedProductReview.review_status)
            .order_by(func.count().desc())
        ).all()
        status_counts = {status or "N/A": int(count) for status, count in status_rows}
        total_rejections = sum(status_counts.values())
        actionable_count = sum(
            status_counts.get(status, 0)
            for status in ("pending", "suggested", "needs_review")
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total rejets suivis", total_rejections)
        c2.metric("Actionnables", actionable_count)
        c3.metric("Validées admin", status_counts.get("validated", 0))
        c4.metric("Validées pipeline", status_counts.get("resolved", 0))

        if total_rejections:
            st.caption(
                f"Taux pipeline: {(status_counts.get('resolved', 0) / total_rejections) * 100:.1f}% | "
                f"Taux admin: {(status_counts.get('validated', 0) / total_rejections) * 100:.1f}%"
            )

        cause_counts: dict[str, int] = {}
        issue_rows = db.execute(select(RejectedProductReview.quality_issues)).all()
        for (issues,) in issue_rows:
            if isinstance(issues, list):
                for issue in issues:
                    cause_counts[str(issue)] = cause_counts.get(str(issue), 0) + 1
            elif isinstance(issues, str) and issues.strip():
                for issue in issues.split(","):
                    issue = issue.strip()
                    if issue:
                        cause_counts[issue] = cause_counts.get(issue, 0) + 1

        col_status, col_causes = st.columns(2)
        with col_status:
            st.markdown("**Répartition des statuts**")
            if status_counts:
                st.dataframe(
                    [{"Statut": status, "Nombre": count} for status, count in status_counts.items()],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Aucun statut disponible.")

        with col_causes:
            st.markdown("**Top causes de rejet**")
            top_causes = sorted(cause_counts.items(), key=lambda item: item[1], reverse=True)[:10]
            if top_causes:
                st.dataframe(
                    [{"Cause": cause, "Nombre": count} for cause, count in top_causes],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Aucune cause disponible.")

        confidence_rows = db.execute(
            select(
                ProductCategorySuggestion.decision_status,
                ProductCategorySuggestion.suggestion_confidence,
            )
            .where(ProductCategorySuggestion.suggestion_confidence.is_not(None))
        ).all()
        buckets = {
            ">= 0.90": 0,
            "0.80 - 0.89": 0,
            "0.70 - 0.79": 0,
            "< 0.70": 0,
        }
        decision_counts: dict[str, int] = {}
        for decision_status, confidence in confidence_rows:
            decision_counts[decision_status or "N/A"] = decision_counts.get(decision_status or "N/A", 0) + 1
            value = float(confidence)
            if value >= 0.90:
                buckets[">= 0.90"] += 1
            elif value >= 0.80:
                buckets["0.80 - 0.89"] += 1
            elif value >= 0.70:
                buckets["0.70 - 0.79"] += 1
            else:
                buckets["< 0.70"] += 1

        col_conf, col_decision = st.columns(2)
        with col_conf:
            st.markdown("**Suggestions par confiance**")
            st.dataframe(
                [{"Confiance": bucket, "Nombre": count} for bucket, count in buckets.items()],
                use_container_width=True,
                hide_index=True,
            )
        with col_decision:
            st.markdown("**Décisions de suggestions**")
            if decision_counts:
                st.dataframe(
                    [{"Décision": status, "Nombre": count} for status, count in decision_counts.items()],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Aucune suggestion disponible.")


def _render_catalog_quality_summary(db) -> None:
    with st.expander("Qualité des données catalogue"):
        stats = db.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT p.code_produit) AS total_products,
                    COUNT(DISTINCT p.code_produit) FILTER (
                        WHERE COALESCE(
                            NULLIF(TRIM(image_url), ''),
                            NULLIF(TRIM(image_small_url), ''),
                            NULLIF(TRIM(image_nutrition_url), '')
                        ) IS NOT NULL
                    ) AS products_with_image,
                    COUNT(DISTINCT p.code_produit) FILTER (
                        WHERE COALESCE(
                            NULLIF(TRIM(image_url), ''),
                            NULLIF(TRIM(image_small_url), ''),
                            NULLIF(TRIM(image_nutrition_url), '')
                        ) IS NULL
                    ) AS products_without_image,
                    COUNT(DISTINCT p.code_produit) FILTER (
                        WHERE v.code_produit IS NOT NULL
                          AND (
                              v.energy_kcal_100g IS NOT NULL
                              OR v.sugars_100g IS NOT NULL
                              OR v.salt_100g IS NOT NULL
                              OR v.saturated_fat_100g IS NOT NULL
                              OR v.fiber_100g IS NOT NULL
                              OR v.proteins_100g IS NOT NULL
                          )
                    ) AS products_with_nutrition,
                    COUNT(DISTINCT p.code_produit) FILTER (
                        WHERE v.code_produit IS NULL
                           OR (
                              v.energy_kcal_100g IS NULL
                              AND v.sugars_100g IS NULL
                              AND v.salt_100g IS NULL
                              AND v.saturated_fat_100g IS NULL
                              AND v.fiber_100g IS NULL
                              AND v.proteins_100g IS NULL
                           )
                    ) AS products_without_nutrition,
                    COUNT(DISTINCT p.code_produit) FILTER (WHERE NULLIF(TRIM(p.nutrition_grade), '') IS NOT NULL) AS products_with_nutriscore,
                    COUNT(DISTINCT p.code_produit) FILTER (WHERE p.nutrition_grade IS NULL OR NULLIF(TRIM(p.nutrition_grade), '') IS NULL) AS products_without_nutriscore,
                    COUNT(DISTINCT p.code_produit) FILTER (WHERE p.nova_group IS NOT NULL) AS products_with_nova,
                    COUNT(DISTINCT p.code_produit) FILTER (WHERE p.nova_group IS NULL) AS products_without_nova,
                    COUNT(DISTINCT p.code_produit) FILTER (WHERE NULLIF(TRIM(p.categorie_principale), '') IS NOT NULL) AS products_with_category,
                    COUNT(DISTINCT p.code_produit) FILTER (WHERE p.categorie_principale IS NULL OR NULLIF(TRIM(p.categorie_principale), '') IS NULL) AS products_without_category,
                    COUNT(DISTINCT p.code_produit) FILTER (WHERE p.id_marque IS NOT NULL) AS products_with_brand,
                    COUNT(DISTINCT p.code_produit) FILTER (WHERE p.id_marque IS NULL) AS products_without_brand,
                    COUNT(DISTINCT pi.code_produit) AS products_with_ingredients
                FROM produit p
                LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
                LEFT JOIN produit_ingredient pi ON p.code_produit = pi.code_produit
                """
            )
        ).mappings().first()

        def stat_int(key: str) -> int:
            return int(stats[key] or 0) if stats else 0

        def rate(count: int, total: int) -> float:
            return (count / total) * 100 if total else 0.0

        total_products = stat_int("total_products")
        products_with_image = stat_int("products_with_image")
        products_without_image = stat_int("products_without_image")
        products_with_nutrition = stat_int("products_with_nutrition")
        products_without_nutrition = stat_int("products_without_nutrition")
        products_with_nutriscore = stat_int("products_with_nutriscore")
        products_without_nutriscore = stat_int("products_without_nutriscore")
        products_with_nova = stat_int("products_with_nova")
        products_without_nova = stat_int("products_without_nova")
        products_with_category = stat_int("products_with_category")
        products_without_category = stat_int("products_without_category")
        products_with_brand = stat_int("products_with_brand")
        products_without_brand = stat_int("products_without_brand")
        products_with_ingredients = stat_int("products_with_ingredients")
        products_without_ingredients = max(total_products - products_with_ingredients, 0)

        quality_dimensions = [
            products_with_image,
            products_with_nutrition,
            products_with_nutriscore,
            products_with_nova,
            products_with_category,
            products_with_brand,
            products_with_ingredients,
        ]
        completeness_rate = (
            sum(rate(value, total_products) for value in quality_dimensions) / len(quality_dimensions)
            if quality_dimensions
            else 0.0
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Produits", total_products)
        c2.metric("Complétude moyenne", f"{completeness_rate:.1f}%")
        c3.metric("Sans image", products_without_image, f"{rate(products_with_image, total_products):.1f}% couverts")
        c4.metric("Sans nutrition", products_without_nutrition, f"{rate(products_with_nutrition, total_products):.1f}% couverts")

        st.markdown("**Couverture par dimension**")
        coverage_rows = [
            ("Images", products_with_image, products_without_image),
            ("Nutrition", products_with_nutrition, products_without_nutrition),
            ("NutriScore", products_with_nutriscore, products_without_nutriscore),
            ("NOVA", products_with_nova, products_without_nova),
            ("Catégorie principale", products_with_category, products_without_category),
            ("Marque", products_with_brand, products_without_brand),
            ("Ingrédients", products_with_ingredients, products_without_ingredients),
        ]
        st.dataframe(
            [
                {
                    "Dimension": label,
                    "Renseignés": present,
                    "Manquants": missing,
                    "Couverture": rate(present, total_products),
                }
                for label, present, missing in coverage_rows
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Couverture": st.column_config.ProgressColumn(
                    "Couverture",
                    min_value=0,
                    max_value=100,
                    format="%.1f%%",
                )
            },
        )

        missing_image_rows = db.execute(
            text(
                """
                SELECT
                    p.code_produit,
                    p.nom_produit,
                    (
                        CASE WHEN COALESCE(NULLIF(TRIM(p.image_url), ''), NULLIF(TRIM(p.image_small_url), ''), NULLIF(TRIM(p.image_nutrition_url), '')) IS NULL THEN 1 ELSE 0 END
                        + CASE WHEN v.code_produit IS NULL OR (
                            v.energy_kcal_100g IS NULL
                            AND v.sugars_100g IS NULL
                            AND v.salt_100g IS NULL
                            AND v.saturated_fat_100g IS NULL
                            AND v.fiber_100g IS NULL
                            AND v.proteins_100g IS NULL
                        ) THEN 1 ELSE 0 END
                        + CASE WHEN p.nutrition_grade IS NULL OR NULLIF(TRIM(p.nutrition_grade), '') IS NULL THEN 1 ELSE 0 END
                        + CASE WHEN p.nova_group IS NULL THEN 1 ELSE 0 END
                        + CASE WHEN p.categorie_principale IS NULL OR NULLIF(TRIM(p.categorie_principale), '') IS NULL THEN 1 ELSE 0 END
                        + CASE WHEN p.id_marque IS NULL THEN 1 ELSE 0 END
                        + CASE WHEN NOT EXISTS (
                            SELECT 1 FROM produit_ingredient pi2 WHERE pi2.code_produit = p.code_produit
                        ) THEN 1 ELSE 0 END
                    ) AS champs_manquants,
                    CONCAT_WS(', ',
                        CASE WHEN COALESCE(NULLIF(TRIM(p.image_url), ''), NULLIF(TRIM(p.image_small_url), ''), NULLIF(TRIM(p.image_nutrition_url), '')) IS NULL THEN 'image' END,
                        CASE WHEN v.code_produit IS NULL OR (
                            v.energy_kcal_100g IS NULL
                            AND v.sugars_100g IS NULL
                            AND v.salt_100g IS NULL
                            AND v.saturated_fat_100g IS NULL
                            AND v.fiber_100g IS NULL
                            AND v.proteins_100g IS NULL
                        ) THEN 'nutrition' END,
                        CASE WHEN p.nutrition_grade IS NULL OR NULLIF(TRIM(p.nutrition_grade), '') IS NULL THEN 'NutriScore' END,
                        CASE WHEN p.nova_group IS NULL THEN 'NOVA' END,
                        CASE WHEN p.categorie_principale IS NULL OR NULLIF(TRIM(p.categorie_principale), '') IS NULL THEN 'catégorie' END,
                        CASE WHEN p.id_marque IS NULL THEN 'marque' END,
                        CASE WHEN NOT EXISTS (
                            SELECT 1 FROM produit_ingredient pi2 WHERE pi2.code_produit = p.code_produit
                        ) THEN 'ingrédients' END
                    ) AS champs_a_completer
                FROM produit p
                LEFT JOIN valeurs_nutritionnelles v ON p.code_produit = v.code_produit
                WHERE COALESCE(
                    NULLIF(TRIM(p.image_url), ''),
                    NULLIF(TRIM(p.image_small_url), ''),
                    NULLIF(TRIM(p.image_nutrition_url), '')
                ) IS NULL
                   OR v.code_produit IS NULL
                   OR p.nutrition_grade IS NULL
                   OR p.nova_group IS NULL
                   OR p.categorie_principale IS NULL
                   OR p.id_marque IS NULL
                   OR NOT EXISTS (
                       SELECT 1 FROM produit_ingredient pi2 WHERE pi2.code_produit = p.code_produit
                   )
                ORDER BY champs_manquants DESC, p.code_produit
                LIMIT 10
                """
            )
        ).mappings().all()

        if missing_image_rows:
            st.markdown("**Produits les plus incomplets**")
            st.dataframe(
                [
                    {
                        "Code": row["code_produit"],
                        "Produit": row["nom_produit"] or "Sans nom",
                        "Champs manquants": row["champs_manquants"],
                        "À compléter": row["champs_a_completer"] or "-",
                    }
                    for row in missing_image_rows
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success("Aucun produit incomplet détecté sur les dimensions suivies.")


def _render_recent_admin_activity(db) -> None:
    with st.expander("Dernières actions admin"):
        status_filter = st.selectbox(
            "Afficher",
            ["validated", "ignored", "resolved", "needs_review", "all"],
            format_func=lambda value: {
                "validated": "Corrections validées admin",
                "ignored": "Produits ignorés",
                "resolved": "Validés par le pipeline",
                "needs_review": "À revoir",
                "all": "Toutes les actions récentes",
            }.get(value, value),
            key="recent_admin_activity_filter",
        )

        query = (
            select(RejectedProductReview, ProductCategorySuggestion)
            .outerjoin(
                ProductCategorySuggestion,
                ProductCategorySuggestion.rejected_id == RejectedProductReview.rejected_id,
            )
            .order_by(RejectedProductReview.updated_at.desc(), RejectedProductReview.rejected_id.desc())
            .limit(50)
        )
        if status_filter != "all":
            query = (
                select(RejectedProductReview, ProductCategorySuggestion)
                .outerjoin(
                    ProductCategorySuggestion,
                    ProductCategorySuggestion.rejected_id == RejectedProductReview.rejected_id,
                )
                .where(RejectedProductReview.review_status == status_filter)
                .order_by(RejectedProductReview.updated_at.desc(), RejectedProductReview.rejected_id.desc())
                .limit(50)
            )

        rows = db.execute(query).all()
        if not rows:
            st.info("Aucune action récente pour ce filtre.")
            return

        table_rows = []
        for rejected, suggestion in rows:
            corrected_payload = rejected.corrected_payload if isinstance(rejected.corrected_payload, dict) else {}
            categories = _payload_text(corrected_payload, "categories")
            if not categories and suggestion:
                categories = suggestion.suggested_categories or ""

            table_rows.append(
                {
                    "Mis à jour": _format_datetime(rejected.updated_at),
                    "Code": rejected.code_produit,
                    "Produit": rejected.product_name or "N/A",
                    "Statut": _humanize_review_status(rejected.review_status),
                    "Catégorie": categories or "N/A",
                    "Validé par": (suggestion.validated_by if suggestion and suggestion.validated_by else "N/A"),
                    "Confiance": (
                        f"{float(suggestion.suggestion_confidence):.2f}"
                        if suggestion and suggestion.suggestion_confidence is not None
                        else "N/A"
                    ),
                    "Source": (suggestion.suggestion_source if suggestion else "N/A"),
                }
            )

        st.dataframe(table_rows, use_container_width=True, hide_index=True)


def _render_pipeline_followup(db) -> None:
    with st.expander("Suivi pipeline des corrections validées"):
        rows = db.execute(
            select(
                RejectedProductReview.code_produit,
                RejectedProductReview.product_name,
                RejectedProductReview.updated_at,
                Product.code_produit.label("loaded_code"),
            )
            .outerjoin(Product, Product.code_produit == RejectedProductReview.code_produit)
            .where(RejectedProductReview.review_status == "validated")
            .order_by(RejectedProductReview.updated_at.desc())
            .limit(100)
        ).all()

        total_validated = len(rows)
        already_loaded = sum(1 for row in rows if row.loaded_code)
        waiting_pipeline = total_validated - already_loaded

        c1, c2, c3 = st.columns(3)
        c1.metric("Validées admin", total_validated)
        c2.metric("Déjà dans produit", already_loaded)
        c3.metric("En attente pipeline", waiting_pipeline)

        if not rows:
            st.info("Aucune correction validée admin à suivre.")
            return

        table_rows = [
            {
                "Code": row.code_produit,
                "Produit": row.product_name or "N/A",
                "Statut pipeline": "Présent dans produit" if row.loaded_code else "En attente Airflow",
                "Validé admin le": _format_datetime(row.updated_at),
            }
            for row in rows
        ]
        st.dataframe(table_rows, use_container_width=True, hide_index=True)


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
    if st.button("Déconnexion", type="secondary"):
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


def _set_admin_mode(mode: str, **state_updates) -> None:
    st.session_state["admin_mode"] = mode
    for key, value in state_updates.items():
        if value is None:
            st.session_state.pop(key, None)
        else:
            st.session_state[key] = value
    st.rerun()


def _admin_shell_style() -> None:
    st.markdown(
        """
        <style>
        .admin-shell-title {
            margin: 0;
            font-size: 1.45rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.15;
        }

        .admin-shell-subtitle {
            margin: 0.2rem 0 0;
            color: #64748b;
            font-size: 0.92rem;
        }

        .admin-section-title {
            margin: 0.8rem 0 0.25rem;
            font-size: 1.05rem;
            font-weight: 750;
            color: #0f172a;
        }

        .admin-section-caption {
            margin: 0 0 0.75rem;
            color: #64748b;
            font-size: 0.9rem;
        }

        .admin-nav-spacer {
            margin-bottom: 0.65rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _admin_header() -> None:
    _admin_shell_style()
    title_col, action_col = st.columns([4, 1])
    with title_col:
        st.markdown(
            """
            <h2 class="admin-shell-title">Administration</h2>
            <p class="admin-shell-subtitle">
                Gestion du catalogue, corrections pipeline et qualité des données.
            </p>
            """,
            unsafe_allow_html=True,
        )
    with action_col:
        _logout_ui()


def _admin_section_nav(active_section: str) -> None:
    nav_catalog, nav_rejections, nav_synonyms, nav_new, _ = st.columns([1.2, 1.4, 1.5, 1.1, 1.6])

    with nav_catalog:
        if st.button(
            "Catalogue",
            type="primary" if active_section == "catalogue" else "secondary",
            use_container_width=True,
        ) and active_section != "catalogue":
            _set_admin_mode("list")

    with nav_rejections:
        if st.button(
            "Corrections",
            type="primary" if active_section == "rejections" else "secondary",
            use_container_width=True,
        ) and active_section != "rejections":
            _set_admin_mode("reject_list")

    with nav_synonyms:
        if st.button(
            "Synonymes",
            type="primary" if active_section == "synonyms" else "secondary",
            use_container_width=True,
        ) and active_section != "synonyms":
            _set_admin_mode("synonyms")

    with nav_new:
        if st.button("Ajouter", type="secondary", use_container_width=True):
            _set_admin_mode("new", admin_code=None)

    st.markdown('<div class="admin-nav-spacer"></div>', unsafe_allow_html=True)


def _admin_section_heading(title: str, caption: str) -> None:
    st.markdown(f'<div class="admin-section-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="admin-section-caption">{caption}</p>', unsafe_allow_html=True)


# =========================
# Admin - Liste Produits
# =========================
def _products_list_ui():
    _admin_section_nav("catalogue")
    _admin_section_heading(
        "Catalogue produits",
        "Recherche, modification et suivi des fiches produit présentes dans le catalogue.",
    )
    _show_admin_flash()

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
        _ensure_rejected_review_schema(db)
        _render_catalog_quality_summary(db)
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
        latest_reviews = _latest_pipeline_reviews_for_codes(
            db,
            [str(product.code_produit) for product in products],
        )

        st.caption(f"Total: **{total}** | Pages: **{total_pages}** | Page: **{page}**")

        st.divider()

        for p in products:
            col1, col2, col3 = st.columns([3, 1, 1])
            latest_review = latest_reviews.get(str(p.code_produit))

            with col1:
                st.write(f"**{p.code_produit}** — {p.nom_produit or ''}")
                st.caption(
                    f"Note nutritionnelle: {p.nutrition_grade or 'N/A'} | "
                    f"Groupe Nova: {p.nova_group or 'N/A'} | "
                    f"Marque: {p.brands or 'N/A'} | "
                    f"Pipeline: {_pipeline_status_label(latest_review)}"
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
    _admin_section_nav("rejections")
    _admin_section_heading(
        "Corrections et rejets",
        "Traitement des produits rejetés, validation des suggestions et suivi du pipeline.",
    )
    _show_admin_flash()

    c1, c2 = st.columns([2, 1])
    with c1:
        q = st.text_input(
            "Recherche code / nom / marque",
            value=st.session_state.get("reject_q", ""),
        )
    with c2:
        _STATUS_OPTIONS = ["actionnable", "all", "pending", "suggested", "validated", "resolved", "ignored", "needs_review"]
        _STATUS_LABELS = {
            "actionnable": "Actionnables (en attente + suggestion + à revoir)",
            "all": "Tous",
            "pending": "En attente",
            "suggested": "Suggestion disponible",
            "validated": "Correction validée (admin)",
            "resolved": "Validé par le pipeline",
            "ignored": "Ignoré",
            "needs_review": "À revoir",
        }
        status_filter = st.selectbox(
            "Statut",
            _STATUS_OPTIONS,
            index=_STATUS_OPTIONS.index(
                st.session_state.get("reject_status", "actionnable")
            ),
            format_func=lambda v: _STATUS_LABELS.get(v, v),
        )

    st.session_state["reject_q"] = q
    st.session_state["reject_status"] = status_filter

    _ACTIONNABLE_STATUSES = {"pending", "suggested", "needs_review"}

    db = SessionLocal()
    try:
        _ensure_rejected_review_schema(db)
        status_counts = dict(
            db.execute(
                select(RejectedProductReview.review_status, func.count())
                .group_by(RejectedProductReview.review_status)
            ).all()
        )
        actionable_total = sum(
            int(status_counts.get(status, 0))
            for status in _ACTIONNABLE_STATUSES
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("À traiter", actionable_total)
        m2.metric("Validées admin", int(status_counts.get("validated", 0)))
        m3.metric("Validées pipeline", int(status_counts.get("resolved", 0)))

        _render_rejection_quality_analysis(db)
        _render_recent_admin_activity(db)
        _render_pipeline_followup(db)

        with st.expander("Validation par lot des suggestions fiables"):
            b1, b2, b3 = st.columns([1, 1, 2])
            with b1:
                confidence_threshold = st.number_input(
                    "Confiance minimale",
                    min_value=0.50,
                    max_value=1.00,
                    value=0.85,
                    step=0.01,
                    format="%.2f",
                )
            candidates = _get_batch_validation_candidates(db, float(confidence_threshold), limit=100)
            diagnostics = _batch_validation_diagnostics(db, float(confidence_threshold))
            with b2:
                st.metric("Candidats", len(candidates))
            with b3:
                st.caption(
                    "Critères: statut actionnable, problème missing_categories, "
                    "suggestion non vide, confiance suffisante, correction testée comme valide."
                )

            st.caption(
                "Diagnostic seuil: "
                f"{diagnostics['suggestions_above_threshold']} suggestion(s) au-dessus du seuil, "
                f"{diagnostics['eligible']} éligible(s), "
                f"{diagnostics['not_actionable_status']} déjà résolue(s)/ignorée(s)/validée(s), "
                f"{diagnostics['already_decided']} déjà décidée(s), "
                f"{diagnostics['not_missing_categories']} autre(s) problème(s), "
                f"{diagnostics['failed_validation']} échoue(nt) au test."
            )

            if candidates:
                preview = ", ".join(
                    f"{rejected.code_produit} → {suggestion.suggested_categories}"
                    for rejected, suggestion, _ in candidates[:5]
                )
                st.caption(f"Aperçu: {preview}")

            if st.button(
                f"Valider {len(candidates)} suggestion(s) fiable(s)",
                disabled=not candidates,
                type="primary",
            ):
                try:
                    now = _utcnow()
                    for rejected, suggestion, corrected_payload in candidates:
                        rejected.corrected_payload = corrected_payload
                        rejected.review_status = "validated"
                        rejected.updated_at = now
                        suggestion.decision_status = "validated"
                        suggestion.validated_by = "auto_batch"
                        suggestion.updated_at = now

                    db.commit()
                    st.session_state["admin_flash"] = {
                        "level": "success",
                        "message": f"{len(candidates)} suggestion(s) fiable(s) validée(s).",
                    }
                    st.rerun()
                except SQLAlchemyError as e:
                    db.rollback()
                    st.error(f"Erreur validation par lot: {e}")

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

        if status_filter == "actionnable":
            query_db = query_db.filter(RejectedProductReview.review_status.in_(_ACTIONNABLE_STATUSES))
        elif status_filter != "all":
            query_db = query_db.filter(RejectedProductReview.review_status == status_filter)

        total_rejected_products = query_db.count()
        rejected_products = (
            query_db.order_by(RejectedProductReview.created_at.desc(), RejectedProductReview.rejected_id.desc())
            .limit(200)
            .all()
        )

        if total_rejected_products > len(rejected_products):
            st.caption(
                f"Résultats: **{total_rejected_products}** "
                f"({len(rejected_products)} affichés, limite 200)"
            )
        else:
            st.caption(f"Résultats: **{total_rejected_products}**")
        st.divider()

        if not rejected_products:
            st.info("Aucun produit rejeté à afficher.")
            return

        for rejected in rejected_products:
            suggestion = _get_active_suggestion_for_code(db, rejected.code_produit)
            raw_payload = rejected.raw_payload if isinstance(rejected.raw_payload, dict) else {}
            corrected_payload = rejected.corrected_payload if isinstance(rejected.corrected_payload, dict) else {}
            col1, col2 = st.columns([5, 1])

            with col1:
                st.write(f"**{rejected.code_produit}** — {rejected.product_name or 'Sans nom'}")
                summary_parts = [
                    f"Problème: {_format_issue_list(rejected.quality_issues) or 'N/A'}",
                    f"Statut: {_humanize_review_status(rejected.review_status)}",
                ]
                if suggestion:
                    confidence = (
                        f"{float(suggestion.suggestion_confidence):.2f}"
                        if suggestion.suggestion_confidence is not None
                        else "N/A"
                    )
                    summary_parts.append(f"Suggestion: {suggestion.suggested_categories or 'N/A'} ({confidence})")
                if corrected_payload:
                    summary_parts.append("Correction: oui")
                st.caption(" | ".join(summary_parts))

            with col2:
                if st.button("✏️ Revoir", key=f"reject_edit_{rejected.rejected_id}"):
                    st.session_state["admin_mode"] = "reject_edit"
                    st.session_state["admin_rejected_id"] = int(rejected.rejected_id)
                    st.rerun()

    except SQLAlchemyError as e:
        st.error(f"Erreur chargement rejets: {e}")
        st.info("Vérifie que les nouvelles tables SQL ont bien été créées dans PostgreSQL.")
    finally:
        db.close()


# =========================
# Suggestion automatique de catégorie
# =========================
def _suggest_categories(db, payload: dict, product_name: str | None) -> list[dict]:
    """
    Retourne une liste de suggestions de catégorie avec leur source :
    1. compared_to_category du payload OpenFoodFacts
    2. Produits similaires par nom dans la base
    """
    suggestions = []

    # Source 1 : compared_to_category
    compared = payload.get("compared_to_category")
    if compared and str(compared).strip().lower() not in {"", "null", "none"}:
        tag = str(compared).strip()
        label = tag.replace("en:", "").replace("-", " ").strip()
        suggestions.append(
            {
                "source": "compared_to_category",
                "categories": label,
                "categories_tags": [tag],
                "categorie_principale": None,
                "confidence": 0.95,
                "detail": tag,
            }
        )

    # Source 2 : produits similaires par nom dans la base
    if product_name and product_name.strip():
        name = product_name.strip()
        try:
            rows = db.execute(
                text("""
                    SELECT p.code_produit, p.nom_produit,
                           COALESCE(NULLIF(p.categorie_principale, ''), 'autres') AS categorie_principale,
                           string_agg(c.categorie, ', ' ORDER BY c.categorie) AS categories
                    FROM produit p
                    JOIN produit_categorie pc ON pc.code_produit = p.code_produit
                    JOIN categorie c ON c.id_categorie = pc.id_categorie
                    WHERE p.nom_produit ILIKE :pattern
                    GROUP BY p.code_produit, p.nom_produit, COALESCE(NULLIF(p.categorie_principale, ''), 'autres')
                    LIMIT 3
                """),
                {"pattern": f"%{name}%"},
            ).fetchall()

            for row in rows:
                if row.categories:
                    suggestions.append({
                        "source": f"produit similaire — {row.nom_produit}",
                        "categories": row.categories,
                        "categories_tags": None,
                        "categorie_principale": row.categorie_principale,
                        "confidence": 0.70,
                        "detail": row.code_produit,
                    })
        except Exception:
            pass

    return suggestions


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
        _ensure_rejected_review_schema(db)
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

        suggestion = _get_active_suggestion_for_code(db, rejected.code_produit)
        payload = rejected.raw_payload if isinstance(rejected.raw_payload, dict) else {}
        corrected_payload = rejected.corrected_payload if isinstance(rejected.corrected_payload, dict) else {}
        issues = rejected.quality_issues if isinstance(rejected.quality_issues, list) else []

        _admin_section_nav("rejections")
        _admin_section_heading(
            f"Revue de correction - {rejected.code_produit}",
            "Comparer la donnée source, la suggestion système et la correction validée.",
        )
        st.caption(
            f"Nom: {rejected.product_name or 'N/A'} | "
            f"Marque: {rejected.brands or 'N/A'} | "
            f"Statut: {_humanize_review_status(rejected.review_status)}"
        )
        st.warning(f"Causes de rejet: {_format_issue_list(issues) or 'N/A'}")

        with st.expander("Voir les données brutes du produit"):
            st.json(payload)

        source_product_name = _payload_field_value(payload, "product_name", "product_name_en", "product_name_fr")
        source_brands = _payload_field_value(payload, "brands", "brands_en", "brands_fr")
        source_categories = _payload_field_value(payload, "categories", "categories_old", "categories_en", "categories_fr")
        source_categories_tags = _payload_field_value(payload, "categories_tags")
        source_primary_category = _payload_field_value(payload, "categorie_principale", "pnns_groups_2", "pnns_groups_1")
        source_quantity = _payload_text(payload, "quantity")
        source_ingredients = _payload_text(payload, "ingredients_text", "ingredients_text_en", "ingredients_text_fr")
        source_allergens = _payload_text(payload, "allergens_tags", "allergens")
        source_labels = _payload_text(payload, "labels_tags", "labels")
        source_image_url = _payload_image_url(payload)
        source_image_nutrition_url = _payload_image_url(payload, "nutrition")
        source_product_url = _payload_text(payload, "url") or _openfoodfacts_product_url(rejected.code_produit)
        source_nutrition_grade = _payload_text(payload, "nutriscore_grade", "nutrition_grade_fr", "nutrition_grade")
        source_nutriscore_score = _payload_text(payload, "nutriscore_score")
        source_nutrition_grade = _normalize_grade_with_score(source_nutrition_grade, source_nutriscore_score)
        source_nova_group = _payload_text(payload, "nova_group")
        source_nutrient_values = {
            nutrient_key: _format_optional_number(_nutrient_number(payload, nutrient_key, nutrient_aliases))
            for nutrient_key, _, nutrient_aliases in _CORE_NUTRIENT_FIELDS
        }

        generated_suggestions = _suggest_categories(db, payload, source_product_name or rejected.product_name)
        selected_preview = None
        manual_category_selection: list[str] = []
        completion = _completion_report(corrected_payload or payload)

        score_col, missing_col = st.columns([1, 3])
        with score_col:
            st.metric("Complétude", f"{completion['percent']}%")
            st.progress(completion["percent"] / 100)
        with missing_col:
            if completion["missing"]:
                st.caption("Champs à compléter: " + ", ".join(completion["missing"]))
            else:
                st.success("La fiche contient les champs essentiels.")

        if source_image_url:
            st.image(source_image_url, width=180)
        else:
            st.info(
                "Aucune image produit n'est présente dans les données source. "
                "Vous pouvez coller une URL d'image manuellement si vous en trouvez une."
            )
            if source_product_url:
                st.caption(f"Page OpenFoodFacts possible: {source_product_url}")

        if suggestion is None and generated_suggestions:
            st.markdown("#### Suggestion automatique disponible")
            choice_idx = st.radio(
                "Suggestion calculée",
                options=range(len(generated_suggestions)),
                format_func=lambda i: (
                    f"{generated_suggestions[i]['categories']} — "
                    f"{generated_suggestions[i]['source']} "
                    f"(confiance {generated_suggestions[i]['confidence']:.2f})"
                ),
                index=0,
            )
            selected_preview = generated_suggestions[choice_idx]
        elif suggestion is None and not generated_suggestions:
            st.info(
                "Aucune suggestion automatique disponible pour ce produit. "
                "Sélectionnez une ou plusieurs catégories existantes ci-dessous."
            )
            all_cats = _get_all_categories(db)
            manual_category_selection = st.multiselect(
                "Catégories (sélection depuis la base)",
                options=[c.categorie for c in all_cats],
                default=[],
                key=f"manual_cats_{rejected_id}",
            )

        current_suggested_categories = (
            suggestion.suggested_categories if suggestion and suggestion.suggested_categories
            else (selected_preview["categories"] if selected_preview else "")
        )
        current_suggested_tags = (
            ", ".join(suggestion.suggested_categories_tags)
            if suggestion and suggestion.suggested_categories_tags
            else (
                ", ".join(selected_preview["categories_tags"])
                if selected_preview and selected_preview.get("categories_tags")
                else ""
            )
        )
        current_suggested_primary = (
            suggestion.suggested_categorie_principale if suggestion and suggestion.suggested_categorie_principale
            else (selected_preview.get("categorie_principale") if selected_preview else "")
        )
        current_suggestion_source = (
            suggestion.suggestion_source if suggestion and suggestion.suggestion_source
            else (selected_preview.get("source") if selected_preview else "")
        )
        current_suggestion_confidence = (
            float(suggestion.suggestion_confidence)
            if suggestion and suggestion.suggestion_confidence is not None
            else (selected_preview.get("confidence") if selected_preview else None)
        )
        corrected_source = corrected_payload or {}
        default_categories = (
            _payload_text(corrected_source, "categories")
            or source_categories
            or current_suggested_categories
            or (", ".join(manual_category_selection) if manual_category_selection else "")
        )
        default_categories_tags = (
            _payload_text(corrected_source, "categories_tags")
            or source_categories_tags
            or current_suggested_tags
            or _tag_label_to_tag(default_categories)
        )
        default_primary_category = (
            _payload_text(corrected_source, "categorie_principale")
            or source_primary_category
            or current_suggested_primary
            or default_categories.split(",")[0].strip().lower()
        )

        with st.container():
            validated_by = st.text_input(
                "Validé par",
                value=(suggestion.validated_by if suggestion and suggestion.validated_by else ""),
            )
            _field_hint("Nom ou initiales de la personne qui valide la correction.")
            st.markdown("**Produit source**")
            c1, c2 = st.columns(2)
            with c1:
                st.text_input("Nom produit", value=source_product_name or rejected.product_name or "", disabled=True)
                st.text_input("Marque", value=source_brands or rejected.brands or "", disabled=True)
                st.text_input("Quantité", value=source_quantity, disabled=True)
                st.text_area("Catégories actuelles", value=source_categories, height=70, disabled=True)
            with c2:
                st.text_area("Tags actuels", value=source_categories_tags, height=70, disabled=True)
                st.text_input("Catégorie principale actuelle", value=source_primary_category, disabled=True)
                st.text_area("Ingrédients actuels", value=source_ingredients, height=70, disabled=True)

            st.markdown("**Suggestion système**")
            s1, s2 = st.columns(2)
            with s1:
                st.text_area(
                    "Catégorie suggérée",
                    value=current_suggested_categories or (", ".join(manual_category_selection) if manual_category_selection else ""),
                    height=70,
                    disabled=True,
                )
                st.text_input(
                    "Source de la suggestion",
                    value=current_suggestion_source or ("sélection manuelle" if manual_category_selection else "N/A"),
                    disabled=True,
                )
            with s2:
                st.text_area(
                    "Tags suggérés",
                    value=current_suggested_tags,
                    height=70,
                    disabled=True,
                )
                st.text_input(
                    "Catégorie principale suggérée",
                    value=current_suggested_primary or "N/A",
                    disabled=True,
                )

            if current_suggestion_confidence is not None:
                st.metric("Confiance de la suggestion", f"{float(current_suggestion_confidence):.2f}")

            st.markdown("**Correction à enregistrer**")
            f1, f2 = st.columns(2)
            with f1:
                corr_product_name = st.text_input(
                    "Nom corrigé",
                    value=_value_from_sources(
                        _payload_text(corrected_source, "product_name", "product_name_en", "product_name_fr"),
                        source_product_name,
                        rejected.product_name,
                    ),
                )
                _field_hint("Nom lisible du produit, sans marque répétée si possible.")
                corr_brands = st.text_input(
                    "Marque corrigée",
                    value=_value_from_sources(
                        _payload_text(corrected_source, "brands", "brands_en", "brands_fr"),
                        source_brands,
                        rejected.brands,
                    ),
                )
                _field_hint("Marque principale; séparer plusieurs marques par une virgule.")
                corr_quantity = st.text_input(
                    "Quantité corrigée",
                    value=_value_from_sources(_payload_text(corrected_source, "quantity"), source_quantity),
                )
                _field_hint("Format attendu: 250 g, 1 l, 330 ml.")
                corr_categories = st.text_area(
                    "Catégories corrigées",
                    value=default_categories,
                    height=80,
                    key=f"corr_categories_{rejected_id}",
                )
                _field_hint("Catégories texte, séparées par des virgules.")
                corr_categories_tags = st.text_area(
                    "Tags catégories corrigés",
                    value=default_categories_tags,
                    height=70,
                    key=f"corr_categories_tags_{rejected_id}",
                )
                _field_hint("Tags OpenFoodFacts, exemple: en:snacks, en:beverages.")
                corr_primary_category = st.text_input(
                    "Catégorie principale corrigée",
                    value=default_primary_category,
                    key=f"corr_primary_category_{rejected_id}",
                )
                _field_hint("Une seule catégorie principale, généralement la première catégorie.")
            with f2:
                corr_ingredients = st.text_area(
                    "Ingrédients corrigés",
                    value=_value_from_sources(
                        _payload_text(corrected_source, "ingredients_text", "ingredients_text_en", "ingredients_text_fr"),
                        source_ingredients,
                    ),
                    height=90,
                )
                _field_hint("Texte d'ingrédients tel qu'affiché sur le produit.")
                corr_allergens = st.text_area(
                    "Allergènes corrigés",
                    value=_value_from_sources(
                        _payload_text(corrected_source, "allergens_tags", "allergens"),
                        source_allergens,
                    ),
                    height=65,
                )
                _field_hint("Tags allergènes si connus, exemple: en:milk, en:soybeans.")
                corr_labels = st.text_area(
                    "Labels corrigés",
                    value=_value_from_sources(_payload_text(corrected_source, "labels_tags", "labels"), source_labels),
                    height=65,
                )
                _field_hint("Labels ou tags, exemple: en:organic, en:gluten-free.")
                corr_image_url = st.text_input(
                    "Image produit",
                    value=_payload_image_url(corrected_source) or source_image_url,
                    help="URL directe d'une image. Ce champ reste vide quand le JSON OpenFoodFacts local ne contient pas d'image.",
                )
                _field_hint("URL http(s) directe vers l'image produit.")
                corr_image_nutrition_url = st.text_input(
                    "Image nutrition",
                    value=_payload_image_url(corrected_source, "nutrition") or source_image_nutrition_url,
                    help="URL directe de l'image nutritionnelle si elle existe dans OpenFoodFacts ou si vous la renseignez manuellement.",
                )
                _field_hint("URL http(s) vers l'image du tableau nutritionnel.")

            n1, n2, n3 = st.columns(3)
            with n1:
                default_nutriscore_score = _value_from_sources(
                    _payload_text(corrected_source, "nutriscore_score"),
                    source_nutriscore_score,
                )
                default_nutrition_grade = _normalize_grade_with_score(
                    _value_from_sources(
                        _payload_text(corrected_source, "nutriscore_grade", "nutrition_grade_fr", "nutrition_grade"),
                        source_nutrition_grade,
                    ),
                    default_nutriscore_score,
                )
                corr_nutrition_grade = st.text_input(
                    "NutriScore corrigé (A-E)",
                    value=default_nutrition_grade,
                )
                _field_hint("Lettre entre A et E; elle sera ajustée si le score indique une autre lettre.")
                corr_nutriscore_score = st.text_input(
                    "Score NutriScore",
                    value=default_nutriscore_score,
                )
                _field_hint("Nombre entier du score NutriScore.")
                corr_nova_group = st.text_input(
                    "NOVA",
                    value=_value_from_sources(_payload_text(corrected_source, "nova_group"), source_nova_group),
                )
                _field_hint("Groupe NOVA entre 1 et 4.")
            nutrient_inputs: dict[str, str] = {}
            nutrient_columns = [n2, n3]
            for idx, (nutrient_key, label, nutrient_aliases) in enumerate(_CORE_NUTRIENT_FIELDS):
                with nutrient_columns[idx % len(nutrient_columns)]:
                    nutrient_inputs[nutrient_key] = st.text_input(
                        f"{label} /100g",
                        value=_format_optional_number(
                            _nutrient_number(corrected_source, nutrient_key, nutrient_aliases)
                            if corrected_source
                            else source_nutrient_values.get(nutrient_key)
                        ),
                    )
                    _field_hint("Valeur numérique pour 100 g ou 100 ml.")

            try:
                preview_payload = _build_corrected_payload(
                    rejected=rejected,
                    payload=payload,
                    product_name=corr_product_name,
                    brands=corr_brands,
                    quantity=corr_quantity,
                    categories=corr_categories,
                    categories_tags=corr_categories_tags,
                    primary_category=corr_primary_category,
                    ingredients_text=corr_ingredients,
                    allergens_tags=corr_allergens,
                    labels_tags=corr_labels,
                    nutrition_grade=_normalize_grade_with_score(corr_nutrition_grade, corr_nutriscore_score),
                    nutriscore_score=corr_nutriscore_score,
                    nova_group=corr_nova_group,
                    image_url=corr_image_url,
                    image_nutrition_url=corr_image_nutrition_url,
                    nutrient_values=nutrient_inputs,
                )
                _render_pipeline_preview(preview_payload)
            except ValueError:
                _render_pipeline_preview(None, "un champ numérique contient une valeur invalide.")

            _DECISION_LABELS = {
                "validated": "Valider la suggestion",
                "rejected": "Refuser la suggestion",
                "needs_review": "À revoir",
            }
            decision_status = st.selectbox(
                "Décision",
                ["validated", "rejected", "needs_review"],
                index=["validated", "rejected", "needs_review"].index(
                    suggestion.decision_status
                    if suggestion and suggestion.decision_status in {"validated", "rejected", "needs_review"}
                    else "validated"
                ),
                format_func=lambda v: _DECISION_LABELS.get(v, v),
            )
            _field_hint("Valider envoie la correction au prochain pipeline.")

            action_test, action_auto, action_save = st.columns([1, 1, 1])
            with action_test:
                test_clicked = st.button("Tester la correction", type="secondary", key=f"test_correction_{rejected_id}")
            with action_auto:
                validate_if_ok = st.button("Valider si test OK", type="primary", key=f"validate_if_ok_{rejected_id}")
            with action_save:
                save = st.button("Enregistrer la décision", key=f"save_decision_{rejected_id}")

        c1, c2 = st.columns(2)
        with c1:
            ignore_clicked = st.button("Ignorer ce rejet", type="secondary")
        with c2:
            back_clicked = st.button("⬅️ Retour à la liste des rejets")

        def build_form_corrected_payload():
            return _build_corrected_payload(
                rejected=rejected,
                payload=payload,
                product_name=corr_product_name,
                brands=corr_brands,
                quantity=corr_quantity,
                categories=corr_categories,
                categories_tags=corr_categories_tags,
                primary_category=corr_primary_category,
                ingredients_text=corr_ingredients,
                allergens_tags=corr_allergens,
                labels_tags=corr_labels,
                nutrition_grade=_normalize_grade_with_score(corr_nutrition_grade, corr_nutriscore_score),
                nutriscore_score=corr_nutriscore_score,
                nova_group=corr_nova_group,
                image_url=corr_image_url,
                image_nutrition_url=corr_image_nutrition_url,
                nutrient_values=nutrient_inputs,
            )

        def save_form_decision(corrected_payload_to_save, force_validated: bool = False):
            nonlocal suggestion
            now = _utcnow()
            selected_source = selected_preview

            if selected_source is None and suggestion is None and manual_category_selection:
                selected_source = {
                    "source": "sélection manuelle admin",
                    "categories": ", ".join(manual_category_selection),
                    "categories_tags": None,
                    "categorie_principale": manual_category_selection[0] if manual_category_selection else None,
                    "confidence": 1.0,
                }

            if suggestion is None:
                suggestion = ProductCategorySuggestion(
                    rejected_id=rejected.rejected_id,
                    code_produit=rejected.code_produit,
                    suggestion_source=(selected_source["source"] if selected_source else "correction manuelle admin"),
                    created_at=now,
                )
                db.add(suggestion)

            suggestion.rejected_id = rejected.rejected_id
            suggestion.code_produit = rejected.code_produit
            suggestion.suggested_categories = corr_categories.strip() or None
            suggestion.suggested_categories_tags = _split_csv(corr_categories_tags)
            suggestion.suggested_categorie_principale = corr_primary_category.strip() or None
            suggestion.suggestion_source = (
                selected_source["source"]
                if selected_source
                else suggestion.suggestion_source
                or "correction manuelle admin"
            )
            suggestion.suggestion_confidence = (
                selected_source.get("confidence")
                if selected_source
                else suggestion.suggestion_confidence
                or 1.0
            )
            suggestion.validated_by = validated_by.strip() or None
            suggestion.decision_status = "validated" if force_validated else decision_status
            suggestion.updated_at = now

            rejected.corrected_payload = corrected_payload_to_save
            if force_validated or decision_status == "validated":
                rejected.review_status = "validated"
            elif decision_status == "rejected":
                rejected.review_status = "needs_review"
            else:
                rejected.review_status = "needs_review"
            rejected.updated_at = now

        if test_clicked:
            try:
                corrected_payload_to_test = build_form_corrected_payload()
                test_issues = _validate_corrected_payload(corrected_payload_to_test)
                test_completion = _completion_report(corrected_payload_to_test)
                if test_issues:
                    st.error("Correction encore non valide pour le pipeline.")
                    st.write("Problèmes restants:")
                    for issue in test_issues:
                        st.write(f"- {_humanize_contract_issue(issue)}")
                else:
                    st.success("Correction valide: le produit devrait pouvoir être repris par le pipeline.")
                st.caption(
                    f"Complétude simulée: {test_completion['percent']}% | "
                    f"Nutriments renseignés: {_corrected_nutrient_count(corrected_payload_to_test)}"
                )
            except ValueError as e:
                st.error(f"Valeur numérique invalide dans la correction: {e}")
            except Exception as e:
                st.error(f"Erreur pendant le test de correction: {e}")

        if validate_if_ok:
            try:
                corrected_payload_to_save = build_form_corrected_payload()
                test_issues = _validate_corrected_payload(corrected_payload_to_save)
                if test_issues:
                    st.error("Correction non enregistrée: le test échoue encore.")
                    st.write("Problèmes restants:")
                    for issue in test_issues:
                        st.write(f"- {_humanize_contract_issue(issue)}")
                    st.stop()

                save_form_decision(corrected_payload_to_save, force_validated=True)
                db.commit()
                st.session_state["admin_flash"] = {
                    "level": "success",
                    "message": f"Correction testée et validée pour le produit {rejected.code_produit}.",
                }
                st.session_state["admin_mode"] = "reject_list"
                st.session_state.pop("admin_rejected_id", None)
                st.rerun()
            except SQLAlchemyError as e:
                db.rollback()
                st.error(f"Erreur validation automatique: {e}")
            except Exception as e:
                db.rollback()
                st.error(f"Erreur inattendue validation automatique: {e}")

        if save:
            try:
                if decision_status == "validated" and not corr_product_name.strip():
                    st.error("Le nom produit est obligatoire pour valider la correction.")
                    st.stop()

                if decision_status == "validated" and not corr_categories.strip():
                    st.error("Au moins une catégorie est obligatoire pour valider la correction.")
                    st.stop()

                if selected_preview is not None and not corr_categories.strip():
                    corr_categories = selected_preview["categories"]
                    corr_categories_tags = ", ".join(selected_preview.get("categories_tags") or [])
                    corr_primary_category = selected_preview.get("categorie_principale") or corr_primary_category

                corrected_payload_to_save = build_form_corrected_payload()
                save_form_decision(corrected_payload_to_save)

                db.commit()
                st.session_state["admin_flash"] = {
                    "level": "success",
                    "message": f"Décision enregistrée pour le produit {rejected.code_produit}.",
                }
                st.session_state["admin_mode"] = "reject_list"
                st.session_state.pop("admin_rejected_id", None)
                st.rerun()
            except SQLAlchemyError as e:
                db.rollback()
                st.error(f"Erreur enregistrement décision: {e}")
            except Exception as e:
                db.rollback()
                st.error(f"Erreur inattendue enregistrement décision: {e}")

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
        nutrition = _get_nutrition_for_product(db, str(p.code_produit)) if p else None

        _admin_section_nav("catalogue")
        _admin_section_heading(
            "Modifier un produit" if is_edit else "Ajouter un produit",
            "Préparer une correction validée admin qui sera reprise par le pipeline.",
        )
        st.info("Les changements sont enregistrés comme corrections validées admin. Ils seront intégrés au catalogue par le pipeline.")
        _show_admin_flash()
        if is_edit and p:
            history = _product_correction_history(db, str(p.code_produit))
            if history:
                latest_review = history[0]
                st.caption(
                    f"Pipeline: {_pipeline_status_label(latest_review)} | "
                    f"Derniere action: {_format_datetime(latest_review.updated_at)}"
                )
                with st.expander("Historique corrections admin"):
                    history_rows = [
                        {
                            "Date": _format_datetime(review.updated_at),
                            "Origine": _humanize_admin_source(review.source_task),
                            "Statut": _humanize_review_status(review.review_status),
                            "Problemes": _format_issue_list(review.quality_issues) or "-",
                        }
                        for review in history
                    ]
                    st.dataframe(history_rows, use_container_width=True, hide_index=True)

        with st.container():
            code_val = st.text_input(
                "Code produit",
                value=(str(p.code_produit) if p else ""),
                disabled=is_edit,
            )
            _field_hint("Code-barres numérique, sans espace ni tiret.")

            name_val = st.text_input(
                "Nom produit",
                value=((p.nom_produit or "") if p else "")
            )
            _field_hint("Nom lisible du produit tel qu'il doit apparaître dans le catalogue.")

            quantity_val = st.text_input(
                "Quantité",
                value=((p.quantite or "") if p else "")
            )
            _field_hint("Format attendu: 250 g, 1 l, 330 ml.")

            grade_val = st.text_input(
                "Note nutritionnelle (A-E)",
                value=((p.nutrition_grade or "") if p else "")
            )
            _field_hint("Lettre entre A et E; elle sera ajustée si le score indique une autre lettre.")

            nutri_score_val = st.text_input(
                "Score Nutriscore (entier)",
                value=(str(p.nutriscore_score) if p and p.nutriscore_score is not None else ""),
            )
            _field_hint("Nombre entier du score NutriScore.")

            nova_val = st.text_input(
                "Groupe Nova (entier)",
                value=(str(p.nova_group) if p and p.nova_group is not None else ""),
            )
            _field_hint("Groupe NOVA entre 1 et 4.")

            url_val = st.text_input(
                "URL",
                value=((p.url or "") if p else "")
            )
            _field_hint("Lien http(s) vers la fiche produit si disponible.")

            image_url_val = st.text_input(
                "URL de l'image",
                value=((p.image_url or "") if p else "")
            )
            _field_hint("Lien http(s) direct vers l'image produit.")

            marque_nom = st.text_input(
                "Marque",
                value=((p.brands or "") if p else "")
            )
            _field_hint("Marque principale; séparer plusieurs marques par une virgule.")

            selected_categories_labels = st.multiselect(
                "Catégories",
                options=category_labels,
                default=selected_categories_default,
            )
            _field_hint("Choisir au moins une catégorie; la première devient la catégorie principale.")

            ingredients_txt = st.text_area(
                "Ingrédients (séparés par , ou |)",
                value=((p.ingredients_text or "") if p else ""),
                height=80,
            )
            _field_hint("Liste d'ingrédients, séparée par virgule ou barre verticale.")

            st.markdown("**Valeurs nutritionnelles /100g**")
            n1, n2, n3 = st.columns(3)
            with n1:
                energy_kcal_val = st.text_input(
                    "Énergie kcal",
                    value=_format_optional_number(nutrition.energy_kcal_100g if nutrition else None),
                )
                _field_hint("Valeur énergétique en kcal pour 100 g ou 100 ml.")
                fat_val = st.text_input(
                    "Matières grasses",
                    value=_format_optional_number(nutrition.fat_100g if nutrition else None),
                )
                _field_hint("Grammes de matières grasses pour 100 g ou 100 ml.")
                saturated_fat_val = st.text_input(
                    "Graisses saturées",
                    value=_format_optional_number(nutrition.saturated_fat_100g if nutrition else None),
                )
                _field_hint("Grammes de graisses saturées pour 100 g ou 100 ml.")
            with n2:
                carbohydrates_val = st.text_input(
                    "Glucides",
                    value=_format_optional_number(nutrition.carbohydrates_100g if nutrition else None),
                )
                _field_hint("Grammes de glucides pour 100 g ou 100 ml.")
                sugars_val = st.text_input(
                    "Sucres",
                    value=_format_optional_number(nutrition.sugars_100g if nutrition else None),
                )
                _field_hint("Grammes de sucres pour 100 g ou 100 ml.")
                fiber_val = st.text_input(
                    "Fibres",
                    value=_format_optional_number(nutrition.fiber_100g if nutrition else None),
                )
                _field_hint("Grammes de fibres pour 100 g ou 100 ml.")
            with n3:
                proteins_val = st.text_input(
                    "Protéines",
                    value=_format_optional_number(nutrition.proteins_100g if nutrition else None),
                )
                _field_hint("Grammes de protéines pour 100 g ou 100 ml.")
                salt_val = st.text_input(
                    "Sel",
                    value=_format_optional_number(nutrition.salt_100g if nutrition else None),
                )
                _field_hint("Grammes de sel pour 100 g ou 100 ml.")

            preview_nutrient_values = {
                "energy_kcal_100g": energy_kcal_val,
                "fat_100g": fat_val,
                "saturated_fat_100g": saturated_fat_val,
                "carbohydrates_100g": carbohydrates_val,
                "sugars_100g": sugars_val,
                "fiber_100g": fiber_val,
                "proteins_100g": proteins_val,
                "salt_100g": salt_val,
            }
            try:
                preview_score = _parse_optional_int(nutri_score_val)
                preview_nova = _parse_optional_int(nova_val)
                preview_grade = _normalize_grade_with_score(grade_val.strip().lower()[:1], nutri_score_val)
                preview_payload = _build_manual_product_payload(
                    code=code_val.strip(),
                    name=name_val,
                    brand=marque_nom,
                    quantity=quantity_val,
                    categories=selected_categories_labels,
                    ingredients=ingredients_txt,
                    grade=preview_grade,
                    nutri_score=preview_score,
                    nova=preview_nova,
                    url=url_val,
                    image_url=image_url_val,
                    nutrient_values=preview_nutrient_values,
                )
                _render_pipeline_preview(preview_payload)
            except ValueError:
                _render_pipeline_preview(None, "un champ numérique contient une valeur invalide.")

            with st.expander("Résumé avant enregistrement"):
                st.write(f"**Code**: {code_val or 'N/A'}")
                st.write(f"**Nom**: {name_val or 'N/A'}")
                st.write(f"**Quantité**: {quantity_val or 'N/A'}")
                st.write(f"**Marque**: {marque_nom or 'N/A'}")
                st.write(f"**Catégories**: {', '.join(selected_categories_labels) or 'N/A'}")
                st.write(f"**NutriScore / NOVA**: {grade_val or 'N/A'} / {nova_val or 'N/A'}")

            ok = st.button("Enregistrer", type="primary", key=f"save_product_{'edit' if is_edit else 'new'}_{code or 'new'}")

        if ok:
            try:
                if not code_val.strip():
                    st.error("Code produit obligatoire.")
                    return

                if not name_val.strip():
                    st.error("Nom produit obligatoire.")
                    return

                code_clean = code_val.strip()
                if not code_clean.isdigit():
                    st.error("Le code produit doit contenir uniquement des chiffres.")
                    return

                grade_clean = grade_val.strip().lower()[:1]
                if grade_clean and grade_clean not in {"a", "b", "c", "d", "e"}:
                    st.error("La note nutritionnelle doit être comprise entre A et E.")
                    return

                nutri_score_clean = _parse_optional_int(nutri_score_val)
                if grade_clean and nutri_score_clean is not None:
                    grade_clean = _normalize_grade_with_score(grade_clean, nutri_score_clean)

                nova_clean = _parse_optional_int(nova_val)
                if nova_clean is not None and nova_clean not in {1, 2, 3, 4}:
                    st.error("Le groupe NOVA doit être entre 1 et 4.")
                    return

                if not _quantity_looks_standardized(quantity_val):
                    st.error("La quantité doit être standardisée, par exemple 250 g ou 1 l.")
                    return

                if not _url_looks_valid(url_val):
                    st.error("L'URL produit doit commencer par http:// ou https://.")
                    return

                if not _url_looks_valid(image_url_val):
                    st.error("L'URL image doit commencer par http:// ou https://.")
                    return

                nutrient_values = {
                    "energy_kcal_100g": energy_kcal_val,
                    "fat_100g": fat_val,
                    "saturated_fat_100g": saturated_fat_val,
                    "carbohydrates_100g": carbohydrates_val,
                    "sugars_100g": sugars_val,
                    "fiber_100g": fiber_val,
                    "proteins_100g": proteins_val,
                    "salt_100g": salt_val,
                }
                parsed_nutrients = {
                    key: _parse_optional_float(value)
                    for key, value in nutrient_values.items()
                }
                for key, value in parsed_nutrients.items():
                    if value is not None and value < 0:
                        st.error("Les valeurs nutritionnelles ne peuvent pas être négatives.")
                        return

                if not is_edit:
                    exists = db.query(Product).filter(Product.code_produit == code_clean).first()
                    if exists:
                        st.session_state["admin_flash"] = {
                            "level": "warning",
                            "message": "Ce code existe déjà. Ouverture du produit en modification.",
                        }
                        st.session_state["admin_mode"] = "edit"
                        st.session_state["admin_code"] = code_clean
                        st.rerun()
                        return

                    manual_payload = _build_manual_product_payload(
                        code=code_clean,
                        name=name_val,
                        brand=marque_nom,
                        quantity=quantity_val,
                        categories=selected_categories_labels,
                        ingredients=ingredients_txt,
                        grade=grade_clean,
                        nutri_score=nutri_score_clean,
                        nova=nova_clean,
                        url=url_val,
                        image_url=image_url_val,
                        nutrient_values=nutrient_values,
                    )
                    validation_issues = _validate_corrected_payload(manual_payload)
                    if validation_issues:
                        st.error("Le produit ne peut pas être envoyé au pipeline.")
                        for issue in validation_issues:
                            st.write(f"- {_humanize_contract_issue(issue)}")
                        return

                    _upsert_admin_product_pipeline_submission(
                        db,
                        code=code_clean,
                        name=name_val,
                        brand=marque_nom,
                        corrected_payload=manual_payload,
                        source_task="streamlit_manual_add",
                        quality_issues=[],
                    )
                    db.commit()
                    st.session_state["admin_flash"] = {
                        "level": "success",
                        "message": "Produit soumis au pipeline comme correction validée admin.",
                    }
                    st.session_state["admin_mode"] = "reject_list"
                    st.rerun()

                edit_payload = _build_manual_product_payload(
                    code=code_clean,
                    name=name_val,
                    brand=marque_nom,
                    quantity=quantity_val,
                    categories=selected_categories_labels,
                    ingredients=ingredients_txt,
                    grade=grade_clean,
                    nutri_score=nutri_score_clean,
                    nova=nova_clean,
                    url=url_val,
                    image_url=image_url_val,
                    nutrient_values=nutrient_values,
                )
                edit_payload["_manual_review"]["source"] = "streamlit_admin_product_edit"
                validation_issues = _validate_corrected_payload(edit_payload)
                if validation_issues:
                    st.error("La modification ne peut pas être envoyée au pipeline.")
                    for issue in validation_issues:
                        st.write(f"- {_humanize_contract_issue(issue)}")
                    return

                _upsert_admin_product_pipeline_submission(
                    db,
                    code=code_clean,
                    name=name_val,
                    brand=marque_nom,
                    corrected_payload=edit_payload,
                    source_task="streamlit_product_edit",
                    quality_issues=[],
                )
                db.commit()
                st.session_state["admin_flash"] = {
                    "level": "success",
                    "message": "Modification soumise au pipeline comme correction validée admin.",
                }
                st.session_state["admin_mode"] = "reject_list"
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
    _admin_section_nav("catalogue")
    _admin_section_heading(
        f"Supprimer produit {code}",
        "La suppression directe est bloquée pour conserver un flux contrôlé par le pipeline.",
    )

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

        st.warning("La suppression directe est désactivée.")
        st.info("Pour respecter le flux projet, une suppression devra passer par une étape pipeline dédiée avant d'être appliquée au catalogue.")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("✏️ Modifier plutôt"):
                st.session_state["admin_mode"] = "edit"
                st.session_state["admin_code"] = code_clean
                st.rerun()

        with c2:
            if st.button("⬅️ Retour"):
                st.session_state["admin_mode"] = "list"
                st.session_state.pop("admin_code", None)
                st.rerun()

    finally:
        db.close()


# =========================
# Synonymes LLM
# =========================
def _synonymes_ui() -> None:
    _TYPE_STYLES = {
        "exact":      ("🟢", "#dcfce7", "#14532d"),
        "traduction": ("🔵", "#dbeafe", "#1e3a5f"),
        "correction": ("🟠", "#ffedd5", "#7c2d12"),
        "variante":   ("⚪", "#f1f5f9", "#334155"),
    }

    st.markdown("""
    <style>
    .syn-kpi-card {
        background: radial-gradient(300px 120px at 10% 0%, rgba(20,184,166,0.10), transparent 80%),
                    radial-gradient(260px 100px at 90% 100%, rgba(245,158,11,0.08), transparent 80%),
                    #ffffff;
        border: 1px solid rgba(15,118,110,0.18);
        border-radius: 14px;
        padding: 1.1rem 1.4rem;
        text-align: center;
    }
    .syn-kpi-label {
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #0f766e;
        margin-bottom: 0.3rem;
    }
    .syn-kpi-value {
        font-size: 2rem;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.1;
    }
    .syn-type-badge {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.04em;
    }
    .syn-table-wrap {
        border: 1px solid rgba(15,118,110,0.15);
        border-radius: 12px;
        overflow: hidden;
        margin-top: 0.8rem;
    }
    .syn-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    .syn-table thead th {
        background: rgba(15,118,110,0.07);
        color: #0f766e;
        font-weight: 700;
        font-size: 0.72rem;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        padding: 0.65rem 1rem;
        border-bottom: 1px solid rgba(15,118,110,0.15);
        text-align: left;
    }
    .syn-table tbody tr { border-bottom: 1px solid #f1f5f9; }
    .syn-table tbody tr:last-child { border-bottom: none; }
    .syn-table tbody tr:hover { background: rgba(20,184,166,0.04); }
    .syn-table td { padding: 0.55rem 1rem; color: #1e293b; vertical-align: middle; }
    .syn-table td.muted { color: #64748b; font-size: 0.83rem; }
    .conf-bar-wrap { background: #e2e8f0; border-radius: 999px; height: 6px; width: 80px; display: inline-block; vertical-align: middle; margin-right: 6px; }
    .conf-bar-fill { height: 6px; border-radius: 999px; background: #0f766e; }
    .syn-filter-box {
        background: #f8fafc;
        border: 1px solid rgba(15,118,110,0.12);
        border-radius: 12px;
        padding: 0.9rem 1.1rem 0.3rem 1.1rem;
        margin-bottom: 0.8rem;
    }
    </style>
    """, unsafe_allow_html=True)

    _admin_section_nav("synonyms")

    st.markdown("""
    <div style="margin-bottom:1.2rem;">
        <div style="font-size:0.78rem;font-weight:700;letter-spacing:0.07em;text-transform:uppercase;color:#0f766e;margin-bottom:0.2rem;">
            Intelligence des ingrédients
        </div>
        <div style="font-size:1.55rem;font-weight:800;color:#0f172a;line-height:1.2;">
            Synonymes ingrédients
        </div>
        <div style="font-size:0.9rem;color:#64748b;margin-top:0.3rem;">
            Correspondances générées par clustering, LLM ou saisie manuelle.
        </div>
    </div>
    """, unsafe_allow_html=True)

    db = SessionLocal()
    try:
        total_row = db.execute(text(
            "SELECT COUNT(*) FROM synonyme_ingredient WHERE nom_synonyme IS NOT NULL AND TRIM(nom_synonyme) <> ''"
        )).scalar() or 0

        canon_row = db.execute(text(
            """
            SELECT
                COUNT(DISTINCT id_standardise)
                + COUNT(DISTINCT CASE WHEN id_standardise IS NULL THEN id_ingredient END)
            FROM synonyme_ingredient
            WHERE nom_synonyme IS NOT NULL
            """
        )).scalar() or 0

        llm_row = db.execute(text(
            "SELECT COUNT(*) FROM synonyme_ingredient WHERE source = 'llm'"
        )).scalar() or 0

        traites_row = db.execute(text(
            """
            SELECT
                COUNT(DISTINCT id_standardise)
                + COUNT(DISTINCT CASE WHEN id_standardise IS NULL THEN id_ingredient END)
            FROM synonyme_ingredient
            WHERE source = 'llm'
            """
        )).scalar() or 0

        m1, m2, m3, m4 = st.columns(4)
        for col, label, value, sub in [
            (m1, "Traités ce run", int(traites_row), None),
            (m2, "Total synonymes", int(total_row), None),
            (m3, "Canoniques couverts", int(canon_row), None),
            (m4, "Générés par LLM", int(llm_row), None),
        ]:
            sub_html = f'<div style="font-size:0.72rem;color:#64748b;margin-top:0.25rem;">{sub}</div>' if sub else ""
            col.markdown(f"""
            <div class="syn-kpi-card">
                <div class="syn-kpi-label">{label}</div>
                <div class="syn-kpi-value">{value}</div>
                {sub_html}
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='margin:1.2rem 0 0.4rem 0;font-size:0.75rem;font-weight:700;letter-spacing:0.07em;text-transform:uppercase;color:#475569;'>Répartition par type</div>", unsafe_allow_html=True)

        dist_rows = db.execute(text(
            """
            SELECT COALESCE(relation_type, 'exact') AS rtype, COUNT(*) AS cnt
            FROM synonyme_ingredient
            GROUP BY rtype
            ORDER BY cnt DESC
            """
        )).all()

        if dist_rows:
            type_cols = st.columns(len(dist_rows))
            type_labels = {"exact": "Exact", "traduction": "Traduction", "correction": "Correction", "variante": "Variante"}
            for col, row in zip(type_cols, dist_rows):
                emoji, bg, fg = _TYPE_STYLES.get(row[0], ("⚪", "#f1f5f9", "#334155"))
                col.markdown(f"""
                <div style="background:{bg};border-radius:12px;padding:0.8rem 1rem;text-align:center;">
                    <div style="font-size:1.4rem;margin-bottom:0.2rem;">{emoji}</div>
                    <div style="font-size:0.72rem;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;color:{fg};margin-bottom:0.25rem;">{type_labels.get(row[0], row[0])}</div>
                    <div style="font-size:1.5rem;font-weight:800;color:{fg};">{int(row[1])}</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<div style='margin:1.4rem 0 0 0;'></div>", unsafe_allow_html=True)

        st.markdown('<div class="syn-filter-box">', unsafe_allow_html=True)
        f1, f2, f3 = st.columns([2, 1, 1])
        with f1:
            search_q = st.text_input("Recherche (synonyme ou canonique)", value="", placeholder="ex: egg, ail, wheat...")
        with f2:
            type_filter = st.selectbox("Type", ["Tous", "exact", "traduction", "correction", "variante"])
        with f3:
            source_filter = st.selectbox("Source", ["Tous", "cluster", "llm", "manual"])
        st.markdown('</div>', unsafe_allow_html=True)

        where_clauses = [
            "si.nom_synonyme IS NOT NULL",
            "TRIM(si.nom_synonyme) <> ''",
        ]
        params: dict = {}

        if search_q.strip():
            where_clauses.append(
                "(LOWER(si.nom_synonyme) LIKE :q OR LOWER(COALESCE(ist.nom_standardise, i.ingredients_nom, '')) LIKE :q)"
            )
            params["q"] = f"%{search_q.strip().lower()}%"

        if type_filter != "Tous":
            where_clauses.append("COALESCE(si.relation_type, 'exact') = :rtype")
            params["rtype"] = type_filter

        if source_filter != "Tous":
            where_clauses.append("COALESCE(si.source, 'manual') = :source")
            params["source"] = source_filter

        where_sql = " AND ".join(where_clauses)

        count_total = db.execute(text(
            f"""
            SELECT COUNT(*)
            FROM synonyme_ingredient si
            LEFT JOIN ingredient i ON i.id_ingredient = si.id_ingredient
            LEFT JOIN ingredient_standardise ist ON ist.id_standardise = si.id_standardise
            WHERE {where_sql}
            """
        ), params).scalar() or 0

        per_page = 50
        page = int(st.session_state.get("syn_page", 1))
        total_pages = max(1, (int(count_total) + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages
            st.session_state["syn_page"] = page

        rows = db.execute(text(
            f"""
            SELECT
                si.nom_synonyme,
                COALESCE(ist.nom_standardise, i.ingredients_nom) AS canonique,
                COALESCE(si.relation_type, 'exact') AS type_rel,
                si.confidence,
                COALESCE(si.source, 'manual') AS source
            FROM synonyme_ingredient si
            LEFT JOIN ingredient i ON i.id_ingredient = si.id_ingredient
            LEFT JOIN ingredient_standardise ist ON ist.id_standardise = si.id_standardise
            WHERE {where_sql}
            ORDER BY si.confidence DESC NULLS LAST, si.nom_synonyme
            LIMIT :lim OFFSET :off
            """
        ), {**params, "lim": per_page, "off": (page - 1) * per_page}).all()

        st.markdown(
            f"<div style='font-size:0.82rem;color:#64748b;margin:0.6rem 0 0.4rem 0;'>"
            f"<b>{int(count_total)}</b> résultats — page <b>{page}</b> / <b>{total_pages}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if rows:
            rows_html = ""
            for r in rows:
                emoji, bg, fg = _TYPE_STYLES.get(r[2], ("⚪", "#f1f5f9", "#334155"))
                badge = f'<span class="syn-type-badge" style="background:{bg};color:{fg};">{emoji} {r[2]}</span>'
                conf_val = float(r[3]) if r[3] is not None else 0.0
                conf_pct = int(conf_val * 100)
                conf_html = (
                    f'<div class="conf-bar-wrap"><div class="conf-bar-fill" style="width:{conf_pct}%;"></div></div>'
                    f'<span style="font-size:0.82rem;color:#475569;">{conf_val:.2f}</span>'
                )
                if r[4] == "llm":
                    source_badge = '<span style="background:#ede9fe;color:#4c1d95;padding:0.15rem 0.5rem;border-radius:999px;font-size:0.72rem;font-weight:700;">LLM</span>'
                elif r[4] == "cluster":
                    source_badge = '<span style="background:#ccfbf1;color:#115e59;padding:0.15rem 0.5rem;border-radius:999px;font-size:0.72rem;font-weight:700;">cluster</span>'
                else:
                    source_badge = '<span style="background:#f1f5f9;color:#475569;padding:0.15rem 0.5rem;border-radius:999px;font-size:0.72rem;font-weight:600;">manuel</span>'
                rows_html += f"""
                <tr>
                    <td><b>{r[0]}</b></td>
                    <td style="color:#0f766e;font-weight:600;">→ {r[1]}</td>
                    <td>{badge}</td>
                    <td>{conf_html}</td>
                    <td>{source_badge}</td>
                </tr>"""

            st.markdown(f"""
            <div class="syn-table-wrap">
                <table class="syn-table">
                    <thead>
                        <tr>
                            <th>Synonyme</th>
                            <th>Canonique</th>
                            <th>Type</th>
                            <th>Confiance</th>
                            <th>Source</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("Aucun synonyme trouvé avec ces filtres.")

        st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
        p1, p2, p3 = st.columns([1, 4, 1])
        with p1:
            if st.button("◀ Précédent", disabled=page <= 1):
                st.session_state["syn_page"] = page - 1
                st.rerun()
        with p3:
            if st.button("Suivant ▶", disabled=page >= total_pages):
                st.session_state["syn_page"] = page + 1
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

    _admin_header()

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

    elif mode == "synonyms":
        _synonymes_ui()

    else:
        st.session_state["admin_mode"] = "list"
        st.rerun()
