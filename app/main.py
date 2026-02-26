###############################################################
# Fichier principal de l'application FastAPI pour OpenFoodFacts
# Version propre : 100% base PostgreSQL, sans CSV/pandas.
###############################################################

from pathlib import Path
import re

import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from barcode import EAN13, Code128
from barcode.writer import ImageWriter

from sqlalchemy import or_, case, func

from app.db import SessionLocal
from app.models import Product


# =========================
# Initialisation FastAPI & templates
# =========================
app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# =========================
# Génération d'images de code-barres (EAN13, Code128)
# =========================
BARCODES_DIR = Path("app/static/barcodes")
BARCODES_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/barcode/{code}.png")
def barcode_png(code: str):
    # Nettoie le code pour ne garder que les chiffres pour EAN13
    digits = re.sub(r"\D", "", code or "")
    writer = ImageWriter()

    safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", code or "") or "unknown"
    file_path = BARCODES_DIR / f"{safe_name}.png"

    if file_path.exists():
        return FileResponse(file_path)

    options = {
        "module_width": 0.13,
        "module_height": 6.5,
        "font_size": 6,
        "text_distance": 3,
        "quiet_zone": 2,
        "write_text": True,
    }

    try:
        # EAN13 attend 13 chiffres
        if len(digits) == 12:
            digits = "0" + digits

        if len(digits) == 13:
            barcode = EAN13(digits, writer=writer)
            barcode.save(str(file_path.with_suffix("")), options)
            return FileResponse(file_path)

        # Sinon, fallback en Code128 sur la chaîne brute
        barcode = Code128(code or "", writer=writer)
        barcode.save(str(file_path.with_suffix("")), options)
        return FileResponse(file_path)

    except Exception:
        return HTMLResponse("Code-barres invalide", status_code=400)


# =========================
# Récupération des images via l'API OpenFoodFacts
# =========================
IMG_CACHE: dict[str, dict] = {}


def off_images(code: str) -> dict:
    code = str(code or "").strip()
    if not code:
        return {"front_small": "", "front_large": ""}

    if code in IMG_CACHE:
        return IMG_CACHE[code]

    imgs = {"front_small": "", "front_large": ""}

    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{code}.json"
        data = requests.get(url, timeout=6).json()
        if data.get("status") == 1:
            p = data.get("product", {}) or {}
            imgs = {
                "front_small": p.get("image_front_small_url") or p.get("image_small_url") or "",
                "front_large": p.get("image_front_url") or p.get("image_url") or "",
            }
    except Exception:
        pass

    if not imgs["front_small"]:
        imgs["front_small"] = imgs["front_large"]
    if not imgs["front_large"]:
        imgs["front_large"] = imgs["front_small"]

    IMG_CACHE[code] = imgs
    return imgs


# =========================
# Formatage numérique pour l'affichage nutritionnel
# =========================

def fmt_num(x) -> str:
    s = str(x or "").strip()
    if not s:
        return ""
    s2 = s.replace(",", ".")
    try:
        v = float(s2)
        if v.is_integer():
            return str(int(v))
        return str(round(v, 2)).rstrip("0").rstrip(".")
    except Exception:
        return s


def build_nutrition_rows(p: dict) -> list[dict]:
    rows: list[dict] = []

    kcal = p.get("energy_kcal_100g", "")
    kj = p.get("energy_kj_100g", "")
    kcal_v = fmt_num(kcal)
    kj_v = fmt_num(kj)
    if kcal_v or kj_v:
        txt = ""
        if kcal_v:
            txt += f"{kcal_v} kcal"
        if kj_v:
            txt += (f" ({kj_v} kJ)" if txt else f"{kj_v} kJ")
        rows.append({"label": "Énergie", "value": txt, "unit": ""})

    mapping = [
        ("fat_100g", "Matières grasses", "g"),
        ("saturated_fat_100g", "Dont saturées", "g"),
        ("carbohydrates_100g", "Glucides", "g"),
        ("sugars_100g", "Dont sucres", "g"),
        ("fiber_100g", "Fibres", "g"),
        ("proteins_100g", "Protéines", "g"),
        ("salt_100g", "Sel", "g"),
    ]

    for key, label, unit in mapping:
        if key in p:
            v = fmt_num(p.get(key, ""))
            if v:
                rows.append({"label": label, "value": v, "unit": unit})

    if "nova_group" in p:
        nv = fmt_num(p.get("nova_group", ""))
        if nv:
            rows.append({"label": "NOVA", "value": nv, "unit": ""})

    return rows


# =========================
# Helpers de transformation Product -> dict pour les templates
# =========================

def product_to_index_dict(p: Product) -> dict:
    """Dictionnaire pour la liste (index.html)."""
    code_str = str(p.code_produit or "")
    d = {
        # Nom utilisé par index.html
        "nom_produit": p.nom_produit or "",
        "brands": p.brands or "",
        "code": code_str,
        "categories": p.categories or "",
        # Champs NutriScore attendus par le template
        "nutriscore_grade": (p.nutrition_grade or "").lower() if p.nutrition_grade else "",
        "nutriscore_score": p.nutriscore_score,
    }
    d["images"] = off_images(code_str)
    return d


def product_to_detail_dict(p: Product) -> dict:
    """Dictionnaire pour la fiche détail (product.html)."""
    code_str = str(p.code_produit or "")

    d: dict = {
        "code": code_str,
        # product.html utilise product_name
        "product_name": p.nom_produit or "",
        "brands": p.brands or "",
        "ingredients_text": p.ingredients_text or "",
        "nutriscore_grade": (p.nutrition_grade or "").lower() if p.nutrition_grade else "",
        "nutriscore_score": p.nutriscore_score,
    }

    # Allergènes texte agrégé (allergens_tags vient de la column_property)
    allergens_txt = p.allergens_tags or ""
    d["allergens_display"] = allergens_txt

    # Nutrition
    nutri_dict = {
        "energy_kcal_100g": p.energy_kcal_100g,
        "fat_100g": p.fat_100g,
        "saturated_fat_100g": p.saturated_fat_100g,
        "carbohydrates_100g": p.carbohydrates_100g,
        "sugars_100g": p.sugars_100g,
        "fiber_100g": p.fiber_100g,
        "proteins_100g": p.proteins_100g,
        "salt_100g": p.salt_100g,
        "nova_group": p.nova_group,
    }
    d["nutrition_rows"] = build_nutrition_rows(nutri_dict)

    # Images & lien OFF
    d["images"] = off_images(code_str)
    d["off_url"] = f"https://world.openfoodfacts.org/product/{code_str}"

    return d


# =========================
# Tri pour la recherche
# =========================

def apply_sort(query, sort: str):
    if sort == "name":
        return query.order_by(Product.nom_produit.asc().nulls_last())

    if sort == "nutriscore":
        # tri par nutrition_grade A->E, puis null à la fin
        order_map = case(
            (Product.nutrition_grade == "a", 1),
            (Product.nutrition_grade == "b", 2),
            (Product.nutrition_grade == "c", 3),
            (Product.nutrition_grade == "d", 4),
            (Product.nutrition_grade == "e", 5),
            else_=999,
        )
        return query.order_by(order_map.asc())

    if sort == "score":
        # plus petit score = meilleur
        return query.order_by(Product.nutriscore_score.asc().nulls_last())

    return query


# =========================
# Routes
# =========================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Page d'accueil : 24 produits au hasard, en privilégiant ceux avec image."""
    db = SessionLocal()
    try:
        per_page = 24

        # Produits avec une image renseignée en base
        with_img_q = db.query(Product).filter(
            (Product.image_url != None) & (Product.image_url != "")  # type: ignore
        )
        count_with_img = with_img_q.count()

        products: list[Product] = []

        # Si on a au moins 24 produits avec image, on tire uniquement dedans
        if count_with_img >= per_page:
            products = (
                with_img_q
                .order_by(func.random())
                .limit(per_page)
                .all()
            )
        else:
            # On prend tous ceux avec image, de manière aléatoire
            products = with_img_q.order_by(func.random()).all()
            remaining = per_page - len(products)

            # On complète avec d'autres produits aléatoires sans contrainte d'image
            if remaining > 0:
                other_q = db.query(Product)
                if products:
                    codes_with_img = [p.code_produit for p in products]
                    other_q = other_q.filter(~Product.code_produit.in_(codes_with_img))

                others = (
                    other_q
                    .order_by(func.random())
                    .limit(remaining)
                    .all()
                )
                products.extend(others)

        # On n'affiche pas de pagination spécifique ici, juste la première "page" aléatoire
        rows = [product_to_index_dict(p) for p in products]

        # Pour rester compatible avec le template, on calcule un total_pages symbolique
        total = db.query(Product).count()
        total_pages = max(1, (total + per_page - 1) // per_page)

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "products": rows,
                "q": "",
                "category": "",
                "allergen": "",
                "use_allergen": False,
                "sort": "name",
                "used_fuzzy": False,
                "page": 1,
                "total_pages": total_pages,
            },
        )
    finally:
        db.close()


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    category: str = "",
    allergen: str = "",
    use_allergen: str = "",
    sort: str = Query("name", pattern="^(name|nutriscore|score)$"),
    page: int = Query(1, ge=1),
):
    """Recherche simple en base : nom, marque, catégories, ingrédients, allergènes."""
    db = SessionLocal()
    try:
        per_page = 24
        qn = (q or "").strip()
        cat = (category or "").strip()
        allg = (allergen or "").strip()
        use_all = (use_allergen == "1")

        if not use_all:
            allg = ""

        query_db = db.query(Product)

        # Filtre texte principal
        if qn:
            like = f"%{qn}%"
            query_db = query_db.filter(
                or_(
                    Product.nom_produit.ilike(like),
                    Product.brands.ilike(like),
                    Product.categories.ilike(like),
                    Product.categories_tags.ilike(like),
                    Product.ingredients_text.ilike(like),
                )
            )

        # Filtre catégorie
        if cat:
            cat_like = f"%{cat}%"
            query_db = query_db.filter(
                or_(
                    Product.categories.ilike(cat_like),
                    Product.categories_tags.ilike(cat_like),
                )
            )

        # Filtre allergènes seulement si case cochée
        if allg:
            all_like = f"%{allg}%"
            query_db = query_db.filter(Product.allergens_tags.ilike(all_like))

        total = query_db.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages

        query_db = apply_sort(query_db, sort)
        products = (
            query_db
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        rows = [product_to_index_dict(p) for p in products]

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "products": rows,
                "q": q,
                "category": category,
                "allergen": allergen,
                "use_allergen": use_all,
                "sort": sort,
                "used_fuzzy": False,
                "page": page,
                "total_pages": total_pages,
            },
        )
    finally:
        db.close()


@app.get("/product/{code}", response_class=HTMLResponse)
def product_detail(request: Request, code: str):
    """Fiche détail d'un produit par code barre."""
    code = (code or "").strip()
    if not code:
        return HTMLResponse("Produit introuvable", status_code=404)

    db = SessionLocal()
    try:
        prod = db.query(Product).filter(Product.code_produit == code).first()
        if not prod:
            return HTMLResponse("Produit introuvable", status_code=404)

        p = product_to_detail_dict(prod)

        return templates.TemplateResponse("product.html", {"request": request, "p": p})
    finally:
        db.close()
