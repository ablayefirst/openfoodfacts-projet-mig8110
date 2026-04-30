import json
import os
import re

from .logger import log
from .config import ENABLE_LLM_CACHE, LLM_CACHE_PATH
from .external_llm import call_llm_batch

CACHE_PATH = LLM_CACHE_PATH
LLM_CACHE = {}

# Cache runtime std (ultra rapide)
GLOBAL_LLM_CACHE = {}
# [FIX-1] Cache runtime synonymes — séparé de GLOBAL_LLM_CACHE
GLOBAL_LLM_SYN_CACHE = {}


# =========================
# 🔑 NORMALISATION CLÉ
# =========================
def normalize_key(value: str) -> str:
    if not value:
        return ""
    value = str(value).lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


# =========================
# 📦 LOAD CACHE
# =========================
def load_cache():
    global LLM_CACHE

    if not ENABLE_LLM_CACHE:
        LLM_CACHE = {}
        log("⚠️ LLM cache DISABLED")
        return

    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                LLM_CACHE = json.load(f)
            log(f"⚡ Cache chargé ({len(LLM_CACHE)} entrées)")
        except Exception:
            LLM_CACHE = {}
    else:
        LLM_CACHE = {}


# =========================
# 💾 SAVE CACHE
# =========================
def save_cache():
    if not ENABLE_LLM_CACHE:
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(CACHE_PATH)), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(LLM_CACHE, f, ensure_ascii=False)
    except Exception as e:
        log(f"⚠️ Cache save failed: {e}")


# =========================
# 🔑 CACHE DISQUE KEY
# =========================
def make_cache_key(text, ingredients):
    base = normalize_key(text)
    ing_part = "|".join(sorted(normalize_key(i) for i in ingredients))
    return f"v3::{base}::{ing_part}"


# =========================
# 🧠 LLM FALLBACK OPTIMISÉ
# =========================
def llm_fallback(text, ingredients):

    if not ingredients or not text:
        # [FIX-3] Fallback vide : synonymes = vides, pas les bruts
        return {
            "ingredients_text": list(ingredients),
            "ingredients_standardized": list(ingredients),
            "ingredients_synonyms": ["" for _ in ingredients],
        }

    # 🔥 1. GLOBAL CACHE FILTER
    filtered = []
    index_map = {}

    for i, ing in enumerate(ingredients):
        key = normalize_key(ing)

        if key in GLOBAL_LLM_CACHE:
            continue

        index_map[len(filtered)] = i
        filtered.append(ing)

    # =========================
    # ⚡ FULL CACHE HIT
    # =========================
    if not filtered:
        log("⚡ FULL GLOBAL CACHE HIT")

        p_std = [
            GLOBAL_LLM_CACHE.get(normalize_key(ing), normalize_key(ing))
            for ing in ingredients
        ]
        # [FIX-2] Cache hit : vrais synonymes depuis GLOBAL_LLM_SYN_CACHE, pas p_std
        p_syn = [
            GLOBAL_LLM_SYN_CACHE.get(normalize_key(ing), "")
            for ing in ingredients
        ]

        return {
            "ingredients_text": list(ingredients),
            "ingredients_standardized": p_std,
            "ingredients_synonyms": p_syn,
        }

    # =========================
    # 🚀 LLM CALL
    # =========================
    log(f"[LLM] Cache {'ENABLED' if ENABLE_LLM_CACHE else 'DISABLED'}")
    log(f"🚀 LLM CALL (BATCH SIZE={len(filtered)})")

    try:
        results = call_llm_batch([{"raw": text, "ingredients": filtered}])
        result = results[0] if results else {}

        l_text = result.get("ingredients_text", []) or []
        l_std = result.get("ingredients_standardized", []) or []
        l_syn = result.get("ingredients_synonyms", []) or []

        # =========================
        # 🔥 STORE GLOBAL CACHE (std + syn)
        # =========================
        for j, ing in enumerate(filtered):
            key = normalize_key(ing)

            if j < len(l_std) and l_std[j]:
                GLOBAL_LLM_CACHE[key] = normalize_key(l_std[j])
            else:
                GLOBAL_LLM_CACHE[key] = key

            # [FIX-1] Stocker les synonymes dans le cache dédié
            if j < len(l_syn) and l_syn[j]:
                GLOBAL_LLM_SYN_CACHE[key] = str(l_syn[j]).strip()
            else:
                GLOBAL_LLM_SYN_CACHE[key] = ""

        # =========================
        # 🔥 REBUILD RESULT
        # =========================
        p_text = []
        p_std = []
        p_syn = []

        for ing in ingredients:
            key = normalize_key(ing)
            std_val = GLOBAL_LLM_CACHE.get(key, key)
            # [FIX-1] Vrais synonymes au lieu de dupliquer std_val
            syn_val = GLOBAL_LLM_SYN_CACHE.get(key, "")

            p_text.append(ing)
            p_std.append(std_val)
            p_syn.append(syn_val)

        final = {
            "ingredients_text": p_text,
            "ingredients_standardized": p_std,
            "ingredients_synonyms": p_syn,
        }

        log(f"[LLM RESULT] STD → {p_std}")
        log(f"[LLM RESULT] SYN → {p_syn}")

        # =========================
        # 💾 DISK CACHE
        # =========================
        if ENABLE_LLM_CACHE:
            key_disk = make_cache_key(text, ingredients)
            LLM_CACHE[key_disk] = final

            if len(LLM_CACHE) % 20 == 0:
                save_cache()

        return final

    except Exception as e:
        log(f"❌ LLM error: {e}")
        # [FIX-3] Fallback erreur : synonymes = vides, pas les bruts
        return {
            "ingredients_text": list(ingredients),
            "ingredients_standardized": list(ingredients),
            "ingredients_synonyms": ["" for _ in ingredients],
        }


# 🔥 INIT
load_cache()