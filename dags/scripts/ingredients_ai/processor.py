from typing import Dict, Any

from .llm import llm_fallback
from .logger import log


def is_simple_ingredient(ing: str) -> bool:
    if not ing:
        return True
    ing = ing.strip()
    words = ing.split()
    return len(words) == 1 or (len(words) == 2 and all(len(w) < 8 for w in words))


def is_complex_phrase(ing: str) -> bool:
    return len(ing.split()) >= 3


BAD_SYNONYMS = {
    "preservative", "flavor", "flavour", "color", "colour", "additive", "ingredient"
}

GENERIC = {
    "preservative", "flavor", "colour", "color", "additive"
}


def process(text: str, corrector, synonym_map: Dict[str, str]) -> Dict[str, Any]:

    from .parser import parse_ingredients, clean_parsed_ingredients
    from .utils import final_cleanup, clean_ingredient, is_invalid, reduce_ingredient

    log("\n========== [PROCESS START] ==========")
    log(f"[RAW TEXT] {text}")

    # ── 1. PARSE ─────────────────────
    parsed = parse_ingredients(text)
    parsed = clean_parsed_ingredients(parsed)
    parsed = final_cleanup(parsed)

    expanded = []
    for ing in parsed:
        if " and " in ing:
            parts = [p.strip() for p in ing.split(" and ") if p.strip()]
            log(f"[SPLIT] {ing} → {parts}")
            expanded.extend(parts)
        else:
            expanded.append(ing)

    parsed = expanded[:15]

    log(f"[PARSE FINAL] {len(parsed)} ingrédients : {parsed}")

    if not parsed:
        return {
            "ingredients_text": [],
            "ingredients_standardized": [],
            "ingredients_synonyms": [],
        }

    # ── 2. EMBEDDING ─────────────────
    if corrector is not None and getattr(corrector, "reference_list", None):
        corrected, match_count = corrector.correct(parsed)
    else:
        corrected = list(parsed)
        match_count = 0

    log(f"[EMBEDDING] matched={match_count}/{len(parsed)}")

    # ── 3. STANDARDIZATION BASE ──────
    standardized = []
    matched_mask = []

    for ing in corrected:
        canonical = synonym_map.get(ing)

        if canonical:
            std = clean_ingredient(canonical)
            matched_mask.append(True)
            log(f"[BASE MATCH] {ing} → {std}")
        else:
            std = clean_ingredient(ing)
            matched_mask.append(False)
            log(f"[BASE RAW] {ing} → {std}")

        standardized.append(std)

    # ── 4. LLM ───────────────────────
    unmatched_indices = [i for i, m in enumerate(matched_mask) if not m]

    llm_text_map = {}
    llm_std_map = {}
    llm_syn_map = {}

    llm_used = 0
    llm_skipped = 0

    if unmatched_indices:

        filtered_indices = []
        filtered_ings = []

        for i in unmatched_indices:
            ing = clean_ingredient(corrected[i])

            if is_simple_ingredient(ing):
                log(f"[FILTER] skip simple → {ing}")
                llm_skipped += 1
                continue

            if is_invalid(ing):
                log(f"[FILTER] skip invalid → {ing}")
                llm_skipped += 1
                continue

            if is_complex_phrase(ing):
                log(f"[COMPLEX DETECTED] {ing}")

            filtered_indices.append(i)
            filtered_ings.append(ing)

        MAX_LLM_BATCH = 3
        if len(filtered_ings) > MAX_LLM_BATCH:
            log(f"[LLM] batch truncated {len(filtered_ings)} → {MAX_LLM_BATCH}")
            filtered_ings = filtered_ings[:MAX_LLM_BATCH]
            filtered_indices = filtered_indices[:MAX_LLM_BATCH]

        if len(filtered_ings) == 0:
            log("[LLM DECISION] skip → empty batch")

        elif len(filtered_ings) == 1:
            ing = filtered_ings[0]

            if is_complex_phrase(ing):
                log(f"[LLM DECISION] use LLM → complex single ({ing})")
            elif len(ing.split()) <= 2:
                log(f"[LLM DECISION] skip → simple single ({ing})")
                filtered_ings = []
                filtered_indices = []
            else:
                log(f"[LLM DECISION] use LLM → single ({ing})")

        else:
            log(f"[LLM DECISION] use LLM → batch size {len(filtered_ings)}")

        log(f"[LLM] final batch={len(filtered_ings)} skipped={llm_skipped}")

        if filtered_ings:
            llm_used = len(filtered_ings)

            log(f"[LLM INPUT] {filtered_ings}")

            try:
                llm_result = llm_fallback(text, filtered_ings)
            except Exception as e:
                log(f"[LLM ERROR] {e}")
                llm_result = {}
        else:
            llm_result = {}

        if isinstance(llm_result, dict):

            l_text = llm_result.get("ingredients_text", []) or []
            l_std = llm_result.get("ingredients_standardized", []) or []
            l_syn = llm_result.get("ingredients_synonyms", []) or []

            for j, orig_idx in enumerate(filtered_indices):

                raw_ing = clean_ingredient(corrected[orig_idx])

                text_val = clean_ingredient(l_text[j]) if j < len(l_text) else raw_ing
                std_val = clean_ingredient(l_std[j]) if j < len(l_std) else raw_ing

                if "|" in std_val:
                    parts = [p.strip() for p in std_val.split("|") if p.strip()]
                    chosen = parts[0] if parts else raw_ing
                    log(f"[FIX MULTI] {raw_ing} → {chosen} (from {parts})")
                    std_val = chosen

                log(f"[LLM MAP] {raw_ing} → {std_val}")

                if std_val in GENERIC:
                    log(f"[BLOCK] {raw_ing} → {std_val}")
                    std_val = raw_ing

                if not std_val or len(std_val) < 2 or is_invalid(std_val):
                    reduced = reduce_ingredient(raw_ing)
                    log(f"[REDUCE] {raw_ing} → {reduced}")
                    std_val = reduced

                llm_std_map[orig_idx] = std_val
                llm_text_map[orig_idx] = text_val

                raw_syn = l_syn[j] if j < len(l_syn) else None
                clean_parts = []
                seen = set()

                if raw_syn:
                    for s in str(raw_syn).split("|"):
                        val = clean_ingredient(s)
                        if val and val not in BAD_SYNONYMS and val not in seen:
                            seen.add(val)
                            clean_parts.append(val)

                # ✅ FIX ICI
                llm_syn_map[orig_idx] = "|".join(clean_parts[:3]) if clean_parts else ""

    # ── 5. MERGE FINAL ───────────────
    final_text = []
    final_standardized = []
    final_synonyms = []

    for i in range(len(corrected)):

        raw_ing = clean_ingredient(corrected[i])

        text_out = clean_ingredient(llm_text_map.get(i, raw_ing))

        std_out = standardized[i] if matched_mask[i] else llm_std_map.get(i, raw_ing)
        std_out = clean_ingredient(std_out)

        # ✅ FIX ICI
        syn_out = llm_syn_map.get(i, "")

        log(f"[MERGE] {raw_ing} → {std_out} | syn: {syn_out}")

        final_text.append(text_out)
        final_standardized.append(std_out)
        final_synonyms.append(syn_out)

    log("========== [PROCESS END] ==========")
    log(f"[STATS] total={len(final_standardized)} llm_used={llm_used} skipped={llm_skipped}\n")

    return {
        "ingredients_text": final_text,
        "ingredients_standardized": final_standardized,
        "ingredients_synonyms": final_synonyms,
    }