###############################################################
# Fichier principal de l'application FastAPI pour OpenFoodFacts
# Version propre : 100% base PostgreSQL, sans CSV/pandas.
###############################################################
import os
from fastapi import Form
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import re

import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER
from barcode import EAN13, Code128
from barcode.writer import ImageWriter
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from sqlalchemy import cast, String
from app.db import SessionLocal
from app.models import (
    Product,
    Marque,
    Categorie,
    Ingredient,
    produit_categorie,
    produit_ingredient,
)


# =========================
# Initialisation FastAPI & templates
# =========================
app = FastAPI()
# =========================
# Sessions (login admin)
# =========================
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-secret-change-me"),
    same_site="lax",
    https_only=False,  # mets True si tu es en HTTPS
)
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

    # Énergie (si un jour tu l'ajoutes en base, tu pourras compléter ici)
    kcal = p.get("energy-kcal_100g", "")
    kj = p.get("energy-kj_100g", "")
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
        ("saturated-fat_100g", "Dont saturées", "g"),
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
        "fat_100g": p.fat_100g,
        "saturated-fat_100g": p.saturated_fat_100g,
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

    try:
        code_int = int(code)
    except ValueError:
        return HTMLResponse("Produit introuvable", status_code=404)

    db = SessionLocal()
    try:
        prod = db.query(Product).filter(Product.code_produit == code_int).first()
        if not prod:
            return HTMLResponse("Produit introuvable", status_code=404)

        p = product_to_detail_dict(prod)

        return templates.TemplateResponse("product.html", {"request": request, "p": p})
    finally:
        db.close()
# =========================
# Admin helpers
# =========================

# ✅ AJOUT IMPORTS MANQUANTS (obligatoires)
from sqlalchemy import select, delete, insert
from starlette import status


def _split_csv(txt: str) -> list[str]:
    if not txt:
        return []
    parts = [p.strip() for p in txt.replace("|", ",").split(",")]
    return [p for p in parts if p]


def _get_or_create_marque(db: Session, marque_nom: str | None) -> Marque | None:
    if not marque_nom:
        return None
    name = marque_nom.strip()
    if not name:
        return None

    # ✅ si doublons => on prend la première ligne (la plus petite id)
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


def _get_or_create_categories(db: Session, categories_txt: str | None) -> list[Categorie]:
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


def _get_or_create_ingredients(db: Session, ingredients_txt: str | None) -> list[Ingredient]:
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


def _replace_product_categories(db: Session, code_produit: int, categories: list[Categorie]) -> None:
    db.execute(
        delete(produit_categorie).where(produit_categorie.c.code_produit == code_produit)
    )
    if categories:
        db.execute(
            insert(produit_categorie),
            [{"code_produit": code_produit, "id_categorie": c.id_categorie} for c in categories],
        )


def _replace_product_ingredients(db: Session, code_produit: int, ingredients: list[Ingredient]) -> None:
    db.execute(
        delete(produit_ingredient).where(produit_ingredient.c.code_produit == code_produit)
    )
    if ingredients:
        db.execute(
            insert(produit_ingredient),
            [{"code_produit": code_produit, "id_ingredient": i.id_ingredient} for i in ingredients],
        )


def admin_required(request: Request):
    """Si pas connecté admin -> redirection /admin/login"""
    if not request.session.get("admin_ok"):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    return None


# ⚠️ IMPORTANT: tu avais 2 fonctions admin_logout.
# On garde UNE seule version: /admin/logout
@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.pop("admin_ok", None)
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


# =========================
# Admin routes
# =========================

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_get(request: Request):
    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "error": ""},
    )


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")

    if username == admin_user and password == admin_pass:
        request.session["admin_ok"] = True
        return RedirectResponse(url="/admin/products", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "error": "Identifiants invalides."},
        status_code=401,
    )


@app.get("/admin/products", response_class=HTMLResponse)
def admin_products(
    request: Request,
    q: str = "",
    page: int = Query(1, ge=1),
):
    # 🔒 protection admin
    redir = admin_required(request)
    if redir:
        return redir

    db = SessionLocal()
    try:
        per_page = 25
        qn = (q or "").strip()

        query_db = db.query(Product)

        # --- FILTRE RECHERCHE ---
        if qn:
            like = f"%{qn}%"

            # ✅ Si l'utilisateur tape un nombre => recherche prioritaire par code exact
            if qn.isdigit():
                code_int = int(qn)
                query_db = query_db.filter(Product.code_produit == code_int)
                query_db = query_db.order_by(Product.code_produit.desc())
            else:
                # ✅ Recherche texte sur champs principaux + code en texte
                query_db = query_db.filter(
                    or_(
                        Product.nom_produit.ilike(like),
                        Product.brands.ilike(like),
                        Product.categories.ilike(like),
                        cast(Product.code_produit, String).ilike(like),
                    )
                )
                query_db = query_db.order_by(Product.nom_produit.asc().nulls_last())
        else:
            query_db = query_db.order_by(Product.code_produit.desc())

        # --- PAGINATION ---
        total = query_db.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages

        products = (
            query_db
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return templates.TemplateResponse(
            "admin/products.html",
            {
                "request": request,
                "products": products,
                "q": q,
                "page": page,
                "total_pages": total_pages,
                "total": total,
            },
        )
    finally:
        db.close()


@app.get("/admin/product/new")
def admin_product_new_get(request: Request):
    redir = admin_required(request)
    if redir:
        return redir

    return templates.TemplateResponse(
        "admin/product_form.html",
        {
            "request": request,
            "title": "Ajouter un produit",
            "action": "/admin/product/new",
            "p": None,
            "is_edit": False,
            "error": "",
        },
    )


@app.post("/admin/product/new")
def admin_product_new_post(
    request: Request,
    code_produit: str = Form(...),
    nom_produit: str = Form(...),
    nutrition_grade: str = Form(None),
    nutriscore_score: str = Form(None),

    marque_nom: str = Form(None),
    categories_txt: str = Form(None),
    ingredients_txt: str = Form(None),
):
    redir = admin_required(request)
    if redir:
        return redir

    db = SessionLocal()
    try:
        code_int = int(code_produit.strip())

        existing = db.get(Product, code_int)
        if existing:
            return templates.TemplateResponse(
                "admin/product_form.html",
                {
                    "request": request,
                    "title": "Ajouter un produit",
                    "action": "/admin/product/new",
                    "p": None,
                    "is_edit": False,
                    "error": "Ce code produit existe déjà.",
                },
            )

        p = Product(
            code_produit=code_int,
            nom_produit=nom_produit.strip(),
            nutrition_grade=(nutrition_grade.strip() if nutrition_grade else None),
            nutriscore_score=(int(nutriscore_score) if nutriscore_score not in (None, "", "None") else None),
        )

        # marque => Marque.brands
        m = _get_or_create_marque(db, marque_nom)
        p.id_marque = (m.id_marque if m else None)

        db.add(p)
        db.flush()

        # catégories / ingrédients via tables d'association
        cats = _get_or_create_categories(db, categories_txt)
        ings = _get_or_create_ingredients(db, ingredients_txt)

        _replace_product_categories(db, p.code_produit, cats)
        _replace_product_ingredients(db, p.code_produit, ings)

        db.commit()
        return RedirectResponse(url="/admin/products", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(
            "admin/product_form.html",
            {
                "request": request,
                "title": "Ajouter un produit",
                "action": "/admin/product/new",
                "p": None,
                "is_edit": False,
                "error": f"Erreur enregistrement: {e}",
            },
        )
    finally:
        db.close()


@app.get("/admin/product/{code}/edit", response_class=HTMLResponse)
def admin_product_edit_get(request: Request, code: str):
    redir = admin_required(request)
    if redir:
        return redir

    try:
        code_int = int((code or "").strip())
    except ValueError:
        return HTMLResponse("Code invalide", status_code=400)

    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.code_produit == code_int).first()
        if not p:
            return HTMLResponse("Produit introuvable", status_code=404)

        return templates.TemplateResponse(
            "admin/product_form.html",
            {
                "request": request,
                "title": f"Modifier produit {code_int}",
                "action": f"/admin/product/{code_int}/edit",
                "p": p,
                "is_edit": True,
                "error": "",
            },
        )
    finally:
        db.close()


@app.post("/admin/product/{code}/edit")
def admin_product_edit_post(
    code: int,
    request: Request,
    nom_produit: str = Form(...),

    marque_nom: str = Form(""),
    categories_txt: str = Form(""),
    ingredients_txt: str = Form(""),

    nutrition_grade: str = Form(""),
    nutriscore_score: str = Form(None),
):
    redir = admin_required(request)
    if redir:
        return redir

    db: Session = SessionLocal()
    p = None
    try:
        p = db.query(Product).filter(Product.code_produit == int(code)).first()
        if not p:
            return RedirectResponse(url="/admin/products", status_code=303)

        # ✅ champs simples
        p.nom_produit = (nom_produit or "").strip()
        p.nutrition_grade = (nutrition_grade or "").strip() or None
        p.nutriscore_score = (int(nutriscore_score) if nutriscore_score not in (None, "", "None") else None)

        # ✅ marque : ton modèle = Marque.brands
        m = _get_or_create_marque(db, marque_nom)
        p.id_marque = (m.id_marque if m else None)

        db.flush()

        # ✅ catégories / ingrédients : tables d'association
        cats = _get_or_create_categories(db, categories_txt)
        ings = _get_or_create_ingredients(db, ingredients_txt)

        _replace_product_categories(db, p.code_produit, cats)
        _replace_product_ingredients(db, p.code_produit, ings)

        db.commit()
        return RedirectResponse(url="/admin/products", status_code=303)

    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(
            "admin/product_form.html",
            {
                "request": request,
                "title": "Modifier un produit",
                "action": f"/admin/product/{code}/edit",
                "p": p,
                "is_edit": True,
                "error": f"Erreur modification: {e}",
            },
        )
    finally:
        db.close()


@app.post("/admin/product/{code}/delete")
def admin_product_delete(request: Request, code: str):
    redir = admin_required(request)
    if redir:
        return redir

    try:
        code_int = int((code or "").strip())
    except ValueError:
        return HTMLResponse("Code invalide", status_code=400)

    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.code_produit == code_int).first()
        if not p:
            return RedirectResponse(url="/admin/products", status_code=303)

        # ⚠️ conseillé: nettoyer les associations avant delete
        db.execute(delete(produit_categorie).where(produit_categorie.c.code_produit == code_int))
        db.execute(delete(produit_ingredient).where(produit_ingredient.c.code_produit == code_int))

        db.delete(p)
        db.commit()

        return RedirectResponse(url="/admin/products", status_code=303)
    finally:
        db.close()