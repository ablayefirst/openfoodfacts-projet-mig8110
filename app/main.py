# =========================
# FastAPI
# =========================
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# =========================
# Data (CSV fallback)
# =========================
import pandas as pd

# =========================
# External API (OpenFoodFacts images)
# =========================
import requests

# =========================
# Utils
# =========================
from pathlib import Path
import re
import unicodedata
from difflib import SequenceMatcher

# =========================
# Barcode
# =========================
from barcode import EAN13, Code128
from barcode.writer import ImageWriter

# =========================
# SQLAlchemy (PostgreSQL)
# =========================
from sqlalchemy import or_, cast, func
from sqlalchemy.types import String as SQLString

# =========================
# Database local modules
# =========================
from app.db import SessionLocal
from app.models import Product

from sqlalchemy import case, cast
from sqlalchemy.types import Integer, String
from app.models import Product

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ✅ Choix source : DB ou CSV
USE_DB = True

# ✅ ton CSV (gardé si USE_DB=False)
CSV_PATH = "data/reduit_bdd.csv"


# =========================
# 1) Lecture robuste (TSV ou CSV)  (gardé)
# =========================
def load_off_file(path: str) -> pd.DataFrame:
    try:
        d = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, engine="python", on_bad_lines="skip")
        if len(d.columns) > 1:
            return d
    except Exception:
        pass
    return pd.read_csv(path, dtype=str, keep_default_na=False, engine="python", on_bad_lines="skip")


df = None
if not USE_DB:
    df = load_off_file(CSV_PATH)


# =========================
# 1.1) Mapping dynamique des colonnes (CSV) (gardé)
# =========================
def first_existing(cols: list[str], default: str = "") -> str:
    if df is None:
        return default
    for c in cols:
        if c in df.columns:
            return c
    return default


COL_CODE = first_existing(["code"], "code")
COL_LC = first_existing(["lc"], "")
COL_BRANDS = first_existing(["brands"], "brands")
COL_CATEGORIES = first_existing(["categories"], "categories")
COL_CATEGORIES_TAGS = first_existing(["categories_tags"], "")
COL_INGREDIENTS = first_existing(["ingredients_text"], "ingredients_text")

COL_ALLERGENS = first_existing(["allergens_tags", "allergens"], "")
COL_TRACES = first_existing(["traces"], "")

COL_NS_GRADE = first_existing(["nutriscore_grade", "off:nutriscore_grade"], "")
COL_NS_SCORE = first_existing(["nutriscore_score", "off:nutriscore_score"], "")

COL_NOVA = first_existing(["nova_group", "nova"], "")

NUTRI_COLS = [
    ("energy-kcal_100g", "Énergie", "kcal"),
    ("energy-kj_100g", "Énergie", "kJ"),
    ("fat_100g", "Matières grasses", "g"),
    ("saturated-fat_100g", "Dont saturées", "g"),
    ("carbohydrates_100g", "Glucides", "g"),
    ("sugars_100g", "Dont sucres", "g"),
    ("fiber_100g", "Fibres", "g"),
    ("proteins_100g", "Protéines", "g"),
    ("salt_100g", "Sel", "g"),
    ("sodium_100g", "Sodium", "g"),
]


# =========================
# 2) Helpers langue (CSV) (gardé)
# =========================
def pick_lang_value(row: pd.Series, base: str, prefer: list[str]) -> str:
    for lang in prefer:
        col = f"{base}_{lang}"
        if col in row.index:
            v = str(row.get(col, "")).strip()
            if v:
                return v

    if COL_LC:
        lc = str(row.get(COL_LC, "")).strip().lower()
        if lc:
            col = f"{base}_{lc}"
            if col in row.index:
                v = str(row.get(col, "")).strip()
                if v:
                    return v

    if base in row.index:
        v = str(row.get(base, "")).strip()
        if v:
            return v

    return ""


def get_product_name(row: pd.Series) -> str:
    return pick_lang_value(row, "product_name", ["fr", "en"])


def get_ingredients(row: pd.Series) -> str:
    return pick_lang_value(row, "ingredients_text", ["fr", "en"])


# =========================
# 3) Normalisation texte (recherche & fautes)
# =========================
def normalize_text(s: str) -> str:
    s = (s or "").lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# CSV enrichissements (gardé)
if not USE_DB and df is not None:
    if "product_name" not in df.columns:
        df["product_name"] = ""
    df["product_name"] = df.apply(get_product_name, axis=1)

    if "ingredients_text" not in df.columns:
        df["ingredients_text"] = ""
    df["ingredients_text"] = df.apply(get_ingredients, axis=1)

    def build_categories_joined(row: pd.Series) -> str:
        c1 = str(row.get(COL_CATEGORIES, "")).strip() if COL_CATEGORIES else ""
        c2 = str(row.get(COL_CATEGORIES_TAGS, "")).strip() if COL_CATEGORIES_TAGS else ""
        return (c1 + " " + c2).strip()

    df["_cat_joined"] = df.apply(build_categories_joined, axis=1)

    def build_allergens_joined(row: pd.Series) -> str:
        a1 = str(row.get(COL_ALLERGENS, "")).strip() if COL_ALLERGENS else ""
        a2 = str(row.get(COL_TRACES, "")).strip() if COL_TRACES else ""
        return (a1 + " " + a2).strip()

    df["_all_joined"] = df.apply(build_allergens_joined, axis=1)

    df["_name_norm"] = df["product_name"].map(normalize_text)
    df["_brand_norm"] = df[COL_BRANDS].astype(str).map(normalize_text) if COL_BRANDS else ""
    df["_cat_norm"] = df["_cat_joined"].astype(str).map(normalize_text)
    df["_ing_norm"] = df["ingredients_text"].astype(str).map(normalize_text)
    df["_all_norm"] = df["_all_joined"].astype(str).map(normalize_text)


# =========================
# 4) Code-barres (EAN13 + fallback Code128)
# =========================
BARCODES_DIR = Path("app/static/barcodes")
BARCODES_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/barcode/{code}.png")
def barcode_png(code: str):
    raw = (code or "").strip()
    digits = re.sub(r"\D", "", raw)

    writer = ImageWriter()

    safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", raw) or "unknown"
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
        if len(digits) == 12:
            digits = "0" + digits
        if len(digits) == 13:
            barcode = EAN13(digits, writer=writer)
            barcode.save(str(file_path.with_suffix("")), options)
            return FileResponse(file_path)

        barcode = Code128(raw, writer=writer)
        barcode.save(str(file_path.with_suffix("")), options)
        return FileResponse(file_path)

    except Exception:
        return HTMLResponse("Code-barres invalide", status_code=400)


# =========================
# 5) Images (API OFF)
# =========================
IMG_CACHE: dict[str, dict] = {}


def off_images(code: str) -> dict:
    code = str(code or "").strip()
    if not code:
        return {"front_small": "", "front_large": "", "ingredients": "", "nutrition": "", "packaging": ""}

    if code in IMG_CACHE:
        return IMG_CACHE[code]

    imgs = {"front_small": "", "front_large": "", "ingredients": "", "nutrition": "", "packaging": ""}

    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{code}.json"
        data = requests.get(url, timeout=6).json()
        if data.get("status") == 1:
            p = data.get("product", {}) or {}
            imgs = {
                "front_small": p.get("image_front_small_url") or p.get("image_small_url") or "",
                "front_large": p.get("image_front_url") or p.get("image_url") or "",
                "ingredients": p.get("image_ingredients_url") or "",
                "nutrition": p.get("image_nutrition_url") or "",
                "packaging": p.get("image_packaging_url") or "",
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
# 5.1) Nutrition en grammes (page détail)
# =========================
def fmt_num(x: str) -> str:
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
    rows = []

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
        ("sodium_100g", "Sodium", "g"),
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
# 6) Recherche (exact + fuzzy fautes)  (gardé pour CSV)
# =========================
def contains_search(frame: pd.DataFrame, query: str) -> pd.DataFrame:
    qn = normalize_text(query)
    if not qn:
        return frame
    tokens = [t for t in qn.split() if t]
    mask_all = None
    for tok in tokens:
        m = (
            frame["_name_norm"].str.contains(tok, na=False) |
            frame["_brand_norm"].str.contains(tok, na=False) |
            frame["_cat_norm"].str.contains(tok, na=False) |
            frame["_ing_norm"].str.contains(tok, na=False)
        )
        mask_all = m if mask_all is None else (mask_all & m)
    return frame[mask_all] if mask_all is not None else frame


def fuzzy_fallback(frame: pd.DataFrame, query: str, limit: int = 24, min_score: float = 0.40) -> pd.DataFrame:
    q = normalize_text(query)
    if not q:
        return frame.head(limit)

    sample = frame
    if len(frame) > 12000:
        sample = frame.sample(12000, random_state=1)

    scored = []
    for idx, r in sample.iterrows():
        s = max(
            SequenceMatcher(None, q, r["_name_norm"]).ratio(),
            SequenceMatcher(None, q, r["_brand_norm"]).ratio(),
        )
        if s >= min_score:
            scored.append((idx, s))

    scored.sort(key=lambda x: x[1], reverse=True)
    top_idx = [i for i, _ in scored[:limit]]
    return frame.loc[top_idx] if top_idx else frame.head(0)

# =========================
# 7.1) Helpers DB (ajout)
# =========================
def product_to_dict_db(p: Product) -> dict:
    d = {
        "code": (p.code or ""),
        "product_name": (getattr(p, "product_name", "") or ""),
        "brands": (getattr(p, "brands", "") or ""),
        "categories": (getattr(p, "categories", "") or ""),
        "categories_tags": (getattr(p, "categories_tags", "") or ""),
        "allergens_tags": (getattr(p, "allergens_tags", "") or ""),
        "ingredients_text": (getattr(p, "ingredients_text", "") or ""),
        # Pour tes templates (tu utilises off:nutriscore_*)
        "off:nutriscore_grade": (getattr(p, "nutriscore_grade", "") or ""),
        "off:nutriscore_score": ("" if getattr(p, "nutriscore_score", None) is None else str(getattr(p, "nutriscore_score"))),
    }

    # Si ta table DB a des colonnes nutrition (optionnel)
    for col, _, _ in NUTRI_COLS:
        if hasattr(p, col):
            d[col] = getattr(p, col) or ""

    if hasattr(p, "nova_group"):
        d["nova_group"] = getattr(p, "nova_group") or ""

    d["images"] = off_images(d["code"])
    return d


def apply_sort_db(query_db, sort: str):
    if sort == "name":
        # tri alphabétique propre (NULL/"" à la fin)
        return query_db.order_by(
            case((Product.product_name == None, 1), else_=0),
            case((Product.product_name == "", 1), else_=0),
            Product.product_name.asc()
        )

    if sort == "nutriscore":
        # A->E, puis vides à la fin
        order_map = case(
            (cast(Product.nutriscore_grade, String) == "a", 1),
            (cast(Product.nutriscore_grade, String) == "b", 2),
            (cast(Product.nutriscore_grade, String) == "c", 3),
            (cast(Product.nutriscore_grade, String) == "d", 4),
            (cast(Product.nutriscore_grade, String) == "e", 5),
            else_=999
        )
        return query_db.order_by(order_map.asc())

    if sort == "score":
        # plus petit score = meilleur (si tu veux l’inverse, mets desc())
        return query_db.order_by(
            case((Product.nutriscore_score == None, 1), else_=0),
            cast(Product.nutriscore_score, Integer).asc()
        )

    return query_db


# =========================
# 8) Routes
# =========================
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # ✅ DB
    if USE_DB:
        db = SessionLocal()
        try:
            products = db.query(Product).limit(24).all()
            rows = [product_to_dict_db(p) for p in products]
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "products": rows,
                    "q": "",
                    "category": "",
                    "allergen": "",
                    "allergen_mode": "exclude",
                    "sort": "name",
                    "order": "asc",
                    "used_fuzzy": False,
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
):

    # ✅ DB
    if USE_DB:
        db = SessionLocal()
        used_fuzzy = False
        try:
            qn = normalize_text(q)
            cat = normalize_text(category)
            allg = normalize_text(allergen)

            # ✅ checkbox: si cochée => use_allergen="1"
            use_all = (use_allergen == "1")

            # ✅ si la checkbox n'est pas cochée -> on ignore allergen
            if not use_all:
                allergen = ""
                allg = ""

            query_db = db.query(Product)

            # recherche contains (nom/marque/cat/ing)
            if qn:
                like = f"%{qn}%"
                query_db = query_db.filter(
                    or_(
                        Product.product_name.ilike(like),
                        Product.brands.ilike(like),
                        Product.categories.ilike(like),
                        Product.categories_tags.ilike(like),
                        Product.ingredients_text.ilike(like),
                    )
                )

            # filtre catégorie
            if cat:
                query_db = query_db.filter(
                    or_(
                        Product.categories.ilike(f"%{cat}%"),
                        Product.categories_tags.ilike(f"%{cat}%"),
                    )
                )

            # ✅ filtre allergènes (uniquement si checkbox cochée)
            if allg:
                contains = Product.allergens_tags.ilike(f"%{allg}%")
                query_db = query_db.filter(contains)  # inclure seulement

            # ✅ tri (sans "order" -> toujours ascendant)
            query_db = apply_sort_db(query_db, sort)

            products = query_db.limit(24).all()

            # fuzzy fallback (si aucun résultat)
            if qn and len(products) == 0:
                used_fuzzy = True
                sample = db.query(Product.code, Product.product_name, Product.brands).limit(12000).all()
                scored = []
                for code_, name_, brand_ in sample:
                    s = max(
                        SequenceMatcher(None, qn, normalize_text(name_ or "")).ratio(),
                        SequenceMatcher(None, qn, normalize_text(brand_ or "")).ratio(),
                    )
                    if s >= 0.40:
                        scored.append((code_, s))
                scored.sort(key=lambda x: x[1], reverse=True)
                top_codes = [c for c, _ in scored[:24]]
                if top_codes:
                    products = db.query(Product).filter(Product.code.in_(top_codes)).all()
                else:
                    products = []

            rows = [product_to_dict_db(p) for p in products]

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
                    "used_fuzzy": used_fuzzy,
                },
            )
        finally:
            db.close()
@app.get("/product/{code}", response_class=HTMLResponse)
def product_detail(request: Request, code: str):
    code = (code or "").strip()

    # ✅ DB (PostgreSQL) si activé
    if USE_DB:
        db = SessionLocal()
        try:
            prod = db.query(Product).filter(Product.code == code).first()
            if not prod:
                return HTMLResponse("Produit introuvable", status_code=404)

            # Produit -> dict (garde tes mêmes clés que les templates)
            p = product_to_dict_db(prod)

            # ✅ Images via API OFF (même si DB n'a pas les urls)
            p["images"] = off_images(code)

            # ✅ Champs unifiés pour template
            p["nutriscore_grade"] = p.get("nutriscore_grade", "") or p.get("off:nutriscore_grade", "")
            p["nutriscore_score"] = p.get("nutriscore_score", "") or p.get("off:nutriscore_score", "")

            # ✅ Allergènes "display" (compatible template)
            p["allergens_display"] = p.get("allergens_tags", "") or p.get("allergens", "")
            traces = p.get("traces", "")
            if traces:
                p["allergens_display"] = (p["allergens_display"] + " | Traces: " + traces).strip(" |")

            # ✅ Nutrition prête pour affichage (g / 100g)
            p["nutrition_rows"] = build_nutrition_rows(p)

            # ✅ Lien OFF
            p["off_url"] = f"https://world.openfoodfacts.org/product/{code}"

            return templates.TemplateResponse("product.html", {"request": request, "p": p})
        finally:
            db.close()

    # ✅ Fallback CSV (si USE_DB=False ou DB indisponible)
    product = df[df[COL_CODE].astype(str) == code]
    if product.empty:
        return HTMLResponse("Produit introuvable", status_code=404)

    row = product.iloc[0]
    p = row.to_dict()

    p["images"] = off_images(code)

    # champs unifiés
    p["nutriscore_grade"] = p.get(COL_NS_GRADE, "") if COL_NS_GRADE else ""
    p["nutriscore_score"] = p.get(COL_NS_SCORE, "") if COL_NS_SCORE else ""

    p["allergens_display"] = p.get(COL_ALLERGENS, "") if COL_ALLERGENS else ""
    if COL_TRACES:
        tr = p.get(COL_TRACES, "")
        if tr:
            p["allergens_display"] = (p["allergens_display"] + " | Traces: " + tr).strip(" |")

    p["nutrition_rows"] = build_nutrition_rows(p)
    p["off_url"] = f"https://world.openfoodfacts.org/product/{code}"

    return templates.TemplateResponse("product.html", {"request": request, "p": p})
