import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("MY_OPENAI_API_KEY"))

MAX_RETRIES = 2
DEBUG_LLM = True


def normalize(x):
    return str(x).strip().lower()


def log_debug(msg):
    if DEBUG_LLM:
        print(msg)


# ══════════════════════════════════════════════════════════════════
# DICTIONNAIRE STATIQUE DE SYNONYMES
# Utilisé quand le LLM est bypassé (ingrédients ≤ 2 mots).
# Garantit des synonymes utiles sans appel réseau.
# Format : { nom_canonique : "syn1|syn2|syn3" }
# ══════════════════════════════════════════════════════════════════
STATIC_SYNONYMS = {
    # Sucres
    "sugar":              "sucrose|cane sugar|white sugar",
    "cane sugar":         "sugar|sucrose",
    "glucose":            "dextrose|glucose syrup",
    "dextrose":           "glucose|corn sugar",
    "fructose":           "fruit sugar|levulose",
    "maltose":            "malt sugar",
    "lactose":            "milk sugar",
    "honey":              "bee honey|natural honey",
    "molasses":           "treacle|black treacle",
    "corn syrup":         "glucose syrup|high fructose corn syrup",
    "invert sugar":       "invert syrup|trimoline",
    "maltitol":           "e965|hydrogenated maltose",
    "sorbitol":           "e420|glucitol",
    "xylitol":            "birch sugar|e967",
    # Matières grasses
    "oil":                "vegetable oil|fat",
    "butter":             "dairy butter|cow butter",
    "fat":                "vegetable fat|shortening",
    "palm oil":           "palm fat|elaeis oil",
    "cocoa butter":       "cacao butter|theobroma oil",
    "canola oil":         "rapeseed oil|colza oil",
    "sunflower oil":      "sunflower seed oil",
    "coconut oil":        "coconut fat|cocos oil",
    "flax oil":           "linseed oil|flaxseed oil",
    "corn oil":           "maize oil",
    "butter oil":         "anhydrous milk fat|clarified butter",
    "palm":               "palm oil|palm fat",
    # Produits laitiers
    "milk":               "whole milk|dairy|cow milk",
    "cream":              "heavy cream|dairy cream",
    "whey":               "milk whey|lactoserum",
    "whey powder":        "dried whey|whey protein",
    "casein":             "milk protein|caseine",
    "milk fat":           "dairy fat|butterfat",
    # Céréales / farines
    "flour":              "wheat flour|white flour",
    "wheat flour":        "all purpose flour|white flour",
    "wheat":              "triticum|common wheat",
    "oat":                "oatmeal|avena",
    "oatmeal":            "rolled oats|oat flakes",
    "corn":               "maize|sweet corn",
    "barley":             "malt barley|hordeum",
    "rice":               "white rice|oryza sativa",
    "starch":             "corn starch|modified starch",
    "wheat starch":       "amylum tritici|wheat carbohydrate",
    # Protéines / légumineuses
    "soy":                "soybean|soya",
    "soya":               "soy|soybean",
    "lecithin":           "soy lecithin|sunflower lecithin|emulsifier",
    "peanuts":            "groundnuts|arachis",
    "almonds":            "sweet almond|prunus amygdalus",
    "hazelnuts":          "filbert|corylus",
    "cashews":            "cashew nuts|anacardium",
    "walnuts":            "english walnut|juglans regia",
    "pecans":             "pecan nuts|carya illinoinensis",
    # Épices et arômes
    "salt":               "sodium chloride|table salt|sea salt",
    "vanilla":            "vanilla extract|vanilla bean",
    "cinnamon":           "cassia|cinnamomum",
    "pepper":             "black pepper|piper nigrum",
    "ginger":             "zingiber officinale|ground ginger",
    "turmeric":           "curcuma|curcumin",
    "paprika":            "sweet pepper|capsicum annuum",
    # Cacao / chocolat
    "cocoa":              "cacao|cocoa powder",
    "chocolate":          "milk chocolate|dark chocolate",
    "cocoa mass":         "chocolate liquor|cocoa liquor",
    "cocoa powder":       "cacao powder|dutch cocoa",
    "milk chocolate":     "sweetened chocolate|chocolate compound",
    # Additifs communs
    "citric acid":        "e330|lemon acid",
    "sodium bicarbonate": "baking soda|e500|bicarbonate of soda",
    "gelatin":            "gelatine|animal gelatin",
    "pectin":             "fruit pectin|e440",
    "water":              "purified water|drinking water",
    "vinegar":            "acetic acid|wine vinegar",
    "yeast":              "active yeast|saccharomyces cerevisiae",
    "egg":                "whole egg|chicken egg",
    "eggs":               "whole eggs|chicken eggs",
    "glycerine":          "glycerol|e422",
    "ascorbic acid":      "vitamin c|e300",
    # Fruits / légumes
    "apple":              "malus domestica|pomme",
    "cranberries":        "vaccinium macrocarpon|sour berries",
    "mangos":             "mangifera indica|tropical fruit",
    "bananas":            "musa paradisiaca|plantain",
    "grapes":             "vitis vinifera|raisins",
    "tomatoes":           "lycopersicon esculentum|tomate",
    # Fromages / laitages
    "cheese":             "dairy cheese|fromage",
    "mozzarella":         "fresh cheese|fior di latte",
    "ricotta":            "whey cheese|fresh ricotta",
}


def get_static_synonyms(ingredient: str) -> str:
    """Retourne les synonymes statiques pour un ingrédient (lookup lowercase)."""
    key = str(ingredient).strip().lower()
    return STATIC_SYNONYMS.get(key, "")


# =========================
# 🔥 PROMPTS
# =========================

def build_transform_prompt(raw_text, ingredients):
    return f"""
You are a strict food ingredient normalization engine.

GOAL:
Convert raw ingredients into clean canonical ingredients.

RULES:
- Output length MUST match input length
- Each ingredient → EXACTLY ONE standardized ingredient
- ingredients_standardized:
  - lowercase
  - single ingredient only
  - NO "|"
- ingredients_synonyms:
  - may contain "|"
  - must be relevant

STRICT SYNONYMS RULES:

- A synonym MUST be a real alternative name of the ingredient
- DO NOT include other ingredients
- DO NOT include components or sub-ingredients
- DO NOT include generic words (ingredient, product, food)
- DO NOT repeat the main ingredient

Examples:

Correct:
milk → dairy|whole milk
sugar → sucrose|cane sugar
lecithin → soy lecithin|emulsifier

Incorrect:
milk → water ❌
bread → wheat flour|yeast ❌
butter → cream|flavor ❌

If no valid synonyms exist:
→ return an empty string ""

CLEANING:
- Remove adjectives (natural, organic, etc.)
- Remove quantities and marketing terms
- Simplify:
  - "milk powder" → "milk"
  - "cane sugar" → "sugar"
  - "soy lecithin" → "lecithin"

MULTI-INGREDIENT CASE:
If input contains multiple ingredients:
→ select ONLY ONE MAIN ingredient

Example:
"vanilla extract milk chocolate" → "vanilla"

FORBIDDEN:
- multiple ingredients in one field
- "|" in standardized
- hallucinations
- changing list length

CONTEXT:
"{raw_text}"

INPUT:
{json.dumps(ingredients, ensure_ascii=False)}

OUTPUT (STRICT JSON ONLY):
{{
  "ingredients_text": [...],
  "ingredients_standardized": [...],
  "ingredients_synonyms": [...]
}}
"""


def build_validate_prompt(raw_text, ingredients):
    return f"""
You are a STRICT ingredient validation engine.

You MUST NOT transform everything.
You MUST ONLY fix errors.

⚠️ YOUR ROLE:

Validate and correct ONLY if needed.

⚠️ RULES:

1. DO NOT rewrite correct values
2. DO NOT change list length
3. ingredients_standardized MUST:
   - contain ONE ingredient only
   - NEVER contain "|"
4. If standardized contains multiple ingredients:
   → keep ONLY the MAIN one

Example:
"vanilla|milk|chocolate" → "vanilla"

5. ingredients_synonyms:
   - can contain "|"
   - must be relevant
   - remove duplicates

6. DO NOT:
   - invent new ingredients
   - remove valid ingredients
   - over-correct

⚠️ IMPORTANT:

If everything is correct → RETURN INPUT AS IS

CONTEXT:
"{raw_text}"

INPUT:
{json.dumps(ingredients, ensure_ascii=False)}

OUTPUT (STRICT JSON ONLY):
{{
  "ingredients_text": [...],
  "ingredients_standardized": [...],
  "ingredients_synonyms": [...]
}}
"""


# =========================
# 🚀 MAIN FUNCTION
# =========================

def call_llm_batch(batch):
    results = []

    for item in batch:

        raw_full = item.get("raw", "") or ""

        if len(raw_full) > 300:
            parts = raw_full.split(",")[:10]
            raw_text = ",".join(parts)
            raw_text = raw_text[:300]
        else:
            raw_text = raw_full

        ingredients = (item.get("ingredients", []) or [])[:8]
        mode = item.get("mode", "transform")

        if not ingredients:
            results.append({
                "ingredients_text": [],
                "ingredients_standardized": [],
                "ingredients_synonyms": [],
            })
            continue

        # =========================
        # ⚡ SKIP LLM (ingrédients simples) → synonymes statiques
        # =========================
        simple_count = sum(1 for ing in ingredients if len(str(ing).split()) <= 2)

        if simple_count == len(ingredients):
            log_debug("⚡ SKIP LLM (all ingredients <= 2 words) → static synonyms")

            normalized = [normalize(x) for x in ingredients]
            # [FIX-❗3] Synonymes statiques au lieu de "" pour les ingrédients simples
            static_syns = [get_static_synonyms(ing) for ing in normalized]

            results.append({
                "ingredients_text": normalized,
                "ingredients_standardized": normalized,
                "ingredients_synonyms": static_syns,
            })
            continue

        # =========================
        # 🔍 LLM NORMAL
        # =========================

        log_debug("\n================= [LLM INPUT] =================")
        log_debug(f"MODE           : {mode}")
        log_debug(f"RAW TEXT       : {raw_text}")
        log_debug(f"INGREDIENTS    : {ingredients}")
        log_debug("==============================================\n")

        if mode == "validate":
            prompt = build_validate_prompt(raw_text, ingredients)
        else:
            prompt = build_transform_prompt(raw_text, ingredients)

        success = False
        attempt = 0
        final_result = None

        while attempt < MAX_RETRIES and not success:
            attempt += 1
            log_debug(f"[LLM] 🔁 Attempt {attempt}")

            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You output ONLY valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    timeout=10
                )

                content = response.choices[0].message.content.strip()
                content = content.replace("```json", "").replace("```", "").strip()

                log_debug("\n[LLM RAW OUTPUT]")
                log_debug(content)
                log_debug("==============================================\n")

                parsed = json.loads(content)

                p_std = parsed.get("ingredients_standardized", []) or []
                p_syn = parsed.get("ingredients_synonyms", []) or []

                n = len(ingredients)

                def align(lst):
                    return [
                        normalize(lst[i]) if i < len(lst) and lst[i]
                        else normalize(ingredients[i])
                        for i in range(n)
                    ]

                p_std = align(p_std)

                fixed_std = []
                for val in p_std:
                    if "|" in val:
                        parts = [p.strip() for p in val.split("|") if p.strip()]
                        val = parts[0] if parts else val
                        log_debug(f"[FIX BACKEND] {parts} → {val}")
                    fixed_std.append(val)

                p_syn_clean = []
                for i in range(n):
                    raw = p_syn[i] if i < len(p_syn) else None

                    if raw:
                        parts = str(raw).replace(",", "|").replace("/", "|").split("|")
                        clean = []
                        seen = set()

                        for p in parts:
                            val = normalize(p)
                            if val and val not in seen:
                                seen.add(val)
                                clean.append(val)

                        p_syn_clean.append("|".join(clean[:3]) if clean else "")
                    else:
                        p_syn_clean.append("")

                final_result = {
                    "ingredients_text": [normalize(x) for x in ingredients],
                    "ingredients_standardized": fixed_std,
                    "ingredients_synonyms": p_syn_clean,
                }

                log_debug("\n========== [LLM OUTPUT] ==========")
                log_debug(f"STANDARDIZED  : {fixed_std}")
                log_debug(f"SYNONYMS      : {p_syn_clean}")
                log_debug("==================================\n")

                success = True

            except Exception as e:
                log_debug(f"❌ [LLM ERROR] {e}")

        if not success:
            log_debug("\n⚠️ [FALLBACK TRIGGERED]")
            final_result = {
                "ingredients_text": [normalize(x) for x in ingredients],
                "ingredients_standardized": [normalize(x) for x in ingredients],
                # [FIX] fallback erreur → vides, pas les bruts (bruts == canonique → tous skippés)
                "ingredients_synonyms": ["" for _ in ingredients],
            }

        results.append(final_result)

    return results