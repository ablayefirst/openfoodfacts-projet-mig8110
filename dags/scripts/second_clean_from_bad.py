#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import PurePosixPath

from sqlalchemy import create_engine

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from transform_to_silver import (
    OUTPUT_COLUMNS,
    build_row,
    evaluate_final_contract,
    get_s3_client,
    iter_json_lines,
    load_normalization_rules,
    write_empty_parquet,
    write_rows_chunk,
    init_ai,
)


# 🔥 NOUVELLE FONCTION
def validate_ingredients_with_llm(row):
    from ingredients_ai.external_llm import call_llm_batch

    ingredients_text = row.get("ingredients_text", [])
    ingredients_std = row.get("ingredients_standardized", [])
    ingredients_syn = row.get("ingredients_synonyms", [])

    if not ingredients_text:
        return row

    print(f"[LLM VALIDATE] INPUT: {ingredients_text}")

    result = call_llm_batch([{
        "raw": " ".join(ingredients_text),
        "ingredients": ingredients_text,
        "mode": "validate"  # 🔥 IMPORTANT
    }])[0]

    new_std = result.get("ingredients_standardized", ingredients_std)
    new_syn = result.get("ingredients_synonyms", ingredients_syn)

    print(f"[LLM VALIDATE] STD BEFORE: {ingredients_std}")
    print(f"[LLM VALIDATE] STD AFTER : {new_std}")

    # 🔥 on modifie UNIQUEMENT ingrédients
    row["ingredients_standardized"] = new_std
    row["ingredients_synonyms"] = new_syn

    return row


def parse_args():
    parser = argparse.ArgumentParser(description="Second cleaning pass from file2_bad JSONL.")
    parser.add_argument("--input-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    parser.add_argument("--input-key", required=True)
    parser.add_argument("--output-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    parser.add_argument("--output-key", required=True)
    return parser.parse_args()


def _join_key(parent: str, child: str) -> str:
    return f"{parent}/{child}" if parent else child


def derive_recovery_keys(final_output_key: str) -> dict[str, str]:
    path = PurePosixPath(final_output_key)
    parent = "" if str(path.parent) == "." else str(path.parent)
    stem = path.stem
    return {
        "recovered_key": _join_key(parent, f"second/{stem}_recovered.parquet"),
        "reject_key": _join_key(parent, f"second/{stem}_reject.jsonl"),
    }


def init_second_clean_stats() -> dict[str, int]:
    return {
        "rows_input": 0,
        "rows_recovered": 0,
        "rows_rejected": 0,
        "invalid_json_lines": 0,
        "empty_lines": 0,
        "missing_code": 0,
        "missing_product_name": 0,
        "missing_categories": 0,
        "missing_categorie_principale": 0,
        "quantity_not_standardized": 0,
        "nutriscore_inconsistent": 0,
        "energy_inconsistent": 0,
        "salt_sodium_inconsistent": 0,
    }


def second_clean_from_bad(
    input_key: str,
    output_key: str,
    input_bucket: str | None = None,
    output_bucket: str | None = None,
    chunk_size: int = 200,
    **_,
):
    if input_bucket is None:
        input_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")
    if output_bucket is None:
        output_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")

    # ── Init AI
    postgres_uri = os.getenv("OPENFOOD_POSTGRES_URI")
    if postgres_uri:
        try:
            engine = create_engine(postgres_uri)
            init_ai(engine)
            print("[AI] ✅ AI initialisée (second_clean)")
        except Exception as e:
            print(f"[AI] ⚠️ Initialisation échouée ({type(e).__name__}: {e}) → ingrédients bruts conservés")
    else:
        print("[AI] ⚠️ POSTGRES_URI absent → AI désactivée (second_clean)")

    keys = derive_recovery_keys(output_key)
    s3 = get_s3_client()
    rules, rules_source = load_normalization_rules()
    obj = s3.get_object(Bucket=input_bucket, Key=input_key)

    stats = init_second_clean_stats()
    transform_stats = {
        "energy_imputed": 0,
        "energy_corrected": 0,
        "salt_imputed": 0,
        "sodium_imputed": 0,
        "sodium_corrected": 0,
        "nutri_grade_imputed": 0,
        "nutri_score_imputed": 0,
        "quantity_invalid_nonpositive": 0,
        "categories_normalized": 0,
        "ingredients_normalized": 0,
        "primary_category_assigned": 0,
        "primary_category_from_tags": 0,
        "primary_category_from_categories": 0,
        "primary_category_default": 0,
        "rule_replacements": 0,
        "rule_filtered": 0,
    }

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as recovered_tmp, tempfile.NamedTemporaryFile(
        suffix=".jsonl",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as reject_tmp:
        recovered_path = recovered_tmp.name
        reject_path = reject_tmp.name

    rows_batch: list[dict[str, object]] = []
    writer = None

    try:
        with open(reject_path, "w", encoding="utf-8") as reject_handle:
            for raw_line in iter_json_lines(obj["Body"]):
                line = raw_line.strip()
                if not line:
                    stats["empty_lines"] += 1
                    continue

                try:
                    product = json.loads(line)
                except json.JSONDecodeError:
                    stats["invalid_json_lines"] += 1
                    continue

                if not isinstance(product, dict):
                    stats["invalid_json_lines"] += 1
                    continue

                stats["rows_input"] += 1

                # 🔥 1. traitement normal (inchangé)
                row = build_row(product, stats=transform_stats, rules=rules, recovery_mode=True)

                # 🔥 2. récupération du travail du first_clean
                if "_cleaned_row" in product:

                    cleaned = product["_cleaned_row"]
                    print("[SECOND CLEAN] Using cleaned_row for ingredients")

                    # 🔥 3. remplacement UNIQUEMENT ingrédients
                    row["ingredients_text"] = cleaned.get("ingredients_text", row.get("ingredients_text"))
                    row["ingredients_standardized"] = cleaned.get("ingredients_standardized", row.get("ingredients_standardized"))
                    row["ingredients_synonyms"] = cleaned.get("ingredients_synonyms", row.get("ingredients_synonyms"))

                    # 🔥 4. validation LLM uniquement ingrédients
                    row = validate_ingredients_with_llm(row)

                issues = evaluate_final_contract(row)

                if issues:
                    rejected_product = dict(product)
                    rejected_product["_quality_contract_issues"] = issues
                    reject_handle.write(json.dumps(rejected_product, ensure_ascii=False) + "\n")
                    stats["rows_rejected"] += 1
                    for issue in issues:
                        stats[issue] = stats.get(issue, 0) + 1
                    continue

                rows_batch.append({column: row.get(column) for column in OUTPUT_COLUMNS})
                stats["rows_recovered"] += 1

                if len(rows_batch) >= chunk_size:
                    writer = write_rows_chunk(writer, rows_batch, recovered_path)
                    rows_batch.clear()
                    import gc
                    gc.collect()

        if rows_batch:
            writer = write_rows_chunk(writer, rows_batch, recovered_path)
            rows_batch = []

    finally:
        if writer is not None:
            writer.close()

    if not os.path.exists(recovered_path) or os.path.getsize(recovered_path) == 0:
        write_empty_parquet(recovered_path)

    try:
        s3.upload_file(recovered_path, output_bucket, keys["recovered_key"])
        s3.upload_file(reject_path, output_bucket, keys["reject_key"])

        stats["rules_loaded"] = 0 if rules_source == "defaults" else 1
        stats.update(transform_stats)

        print(
            "Second cleaning summary: "
            f"input={stats['rows_input']}, recovered={stats['rows_recovered']}, rejected={stats['rows_rejected']}"
        )

        return {
            "recovered_key": keys["recovered_key"],
            "reject_key": keys["reject_key"],
            "output_bucket": output_bucket,
            **stats,
        }

    finally:
        for path in (recovered_path, reject_path):
            if os.path.exists(path):
                os.remove(path)


def main():
    args = parse_args()
    second_clean_from_bad(
        input_bucket=args.input_bucket,
        input_key=args.input_key,
        output_bucket=args.output_bucket,
        output_key=args.output_key,
    )


if __name__ == "__main__":
    main()