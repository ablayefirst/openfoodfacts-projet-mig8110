#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import PurePosixPath

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from transform_to_silver import (
    OUTPUT_COLUMNS,
    apply_validated_category_suggestion,
    build_row,
    evaluate_final_contract,
    get_s3_client,
    infer_import_type,
    iter_json_lines,
    load_validated_category_suggestions,
    load_normalization_rules,
    normalize_code,
    resolve_rejected_product_reviews,
    update_category_suggestion_status,
    upsert_rejected_product_reviews,
    write_empty_parquet,
    write_rows_chunk,
)


def parse_args():
    parser = argparse.ArgumentParser(description="First cleaning pass from Bronze JSONL.")
    parser.add_argument("--input-bucket", default=os.getenv("MINIO_BUCKET_BRONZE", "bronze"))
    parser.add_argument("--input-key", required=True)
    parser.add_argument("--output-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    parser.add_argument("--output-key", required=True, help="Final silver parquet key used as naming base.")
    return parser.parse_args()


def _join_key(parent: str, child: str) -> str:
    return f"{parent}/{child}" if parent else child


def derive_cleaning_keys(final_output_key: str) -> dict[str, str]:
    path = PurePosixPath(final_output_key)
    parent = "" if str(path.parent) == "." else str(path.parent)
    stem = path.stem
    return {
        "good_key": _join_key(parent, f"first/{stem}_file1_good.parquet"),
        "bad_key": _join_key(parent, f"first/{stem}_file2_bad.jsonl"),
    }


def init_first_clean_stats() -> dict[str, int]:
    return {
        "rows_input": 0,
        "rows_good": 0,
        "rows_bad": 0,
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
        "category_suggestions_loaded": 0,
        "category_suggestions_applied": 0,
        "suggested_primary_category_overrides": 0,
    }


def first_clean_from_bronze(
    input_key: str,
    output_key: str,
    input_bucket: str | None = None,
    output_bucket: str | None = None,
    chunk_size: int = 5000,
    **_,
):
    if input_bucket is None:
        input_bucket = os.getenv("MINIO_BUCKET_BRONZE", "bronze")
    if output_bucket is None:
        output_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")

    keys = derive_cleaning_keys(output_key)
    s3 = get_s3_client()
    rules, rules_source = load_normalization_rules()
    category_suggestions = load_validated_category_suggestions()
    obj = s3.get_object(Bucket=input_bucket, Key=input_key)
    source_run_id = os.getenv("AIRFLOW_CTX_DAG_RUN_ID")
    import_type = infer_import_type()

    stats = init_first_clean_stats()
    stats["category_suggestions_loaded"] = len(category_suggestions)
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
        "category_suggestions_applied": 0,
        "suggested_primary_category_overrides": 0,
        "rule_replacements": 0,
        "rule_filtered": 0,
    }

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as good_tmp, tempfile.NamedTemporaryFile(
        suffix=".jsonl",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as bad_tmp:
        good_path = good_tmp.name
        bad_path = bad_tmp.name

    rows_batch: list[dict[str, object]] = []
    rejected_reviews: list[dict[str, object]] = []
    resolved_suggested_codes: set[str] = set()
    writer = None

    try:
        with open(bad_path, "w", encoding="utf-8") as bad_handle:
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
                code = normalize_code(product.get("code"))
                suggestion = category_suggestions.get(code) if code is not None else None
                corrected_product, suggestion_applied = apply_validated_category_suggestion(
                    product,
                    suggestion,
                    stats=transform_stats,
                )
                row = build_row(
                    corrected_product,
                    stats=transform_stats,
                    rules=rules,
                    recovery_mode=False,
                    category_suggestion=suggestion,
                )
                issues = evaluate_final_contract(row)

                if issues:
                    bad_product = dict(corrected_product)
                    bad_product["_quality_contract_issues"] = issues
                    bad_handle.write(json.dumps(bad_product, ensure_ascii=False) + "\n")
                    stats["rows_bad"] += 1
                    rejected_reviews.append(
                        {
                            "code_produit": row.get("code") or product.get("code"),
                            "product_name": row.get("product_name") or product.get("product_name"),
                            "brands": row.get("brands") or product.get("brands"),
                            "raw_payload": bad_product,
                            "quality_issues": issues,
                            "review_status": "needs_review" if suggestion_applied else "pending",
                        }
                    )
                    for issue in issues:
                        stats[issue] = stats.get(issue, 0) + 1
                    continue

                rows_batch.append({column: row.get(column) for column in OUTPUT_COLUMNS})
                stats["rows_good"] += 1
                if suggestion_applied and row.get("code"):
                    resolved_suggested_codes.add(str(row["code"]))
                if len(rows_batch) >= chunk_size:
                    writer = write_rows_chunk(writer, rows_batch, good_path)
                    rows_batch = []

        if rows_batch:
            writer = write_rows_chunk(writer, rows_batch, good_path)
            rows_batch = []
    finally:
        if writer is not None:
            writer.close()

    if not os.path.exists(good_path) or os.path.getsize(good_path) == 0:
        write_empty_parquet(good_path)

    try:
        s3.upload_file(good_path, output_bucket, keys["good_key"])
        s3.upload_file(bad_path, output_bucket, keys["bad_key"])
        upsert_rejected_product_reviews(
            rejected_reviews,
            source_task="first_clean_from_bronze",
            source_run_id=source_run_id,
            import_type=import_type,
            rules=rules,
        )
        resolve_rejected_product_reviews(resolved_suggested_codes)
        update_category_suggestion_status(resolved_suggested_codes, "applied")
        stats["rules_loaded"] = 0 if rules_source == "defaults" else 1
        stats.update(transform_stats)

        print(
            "First cleaning summary: "
            f"input={stats['rows_input']}, good={stats['rows_good']}, bad={stats['rows_bad']}, "
            f"invalid_json={stats['invalid_json_lines']}, empty_lines={stats['empty_lines']}"
        )
        print(
            f"Uploaded first-clean outputs to s3://{output_bucket}/{keys['good_key']} "
            f"and s3://{output_bucket}/{keys['bad_key']}"
        )
        return {
            "good_key": keys["good_key"],
            "bad_key": keys["bad_key"],
            "output_bucket": output_bucket,
            **stats,
        }
    finally:
        for path in (good_path, bad_path):
            if os.path.exists(path):
                os.remove(path)


def main():
    args = parse_args()
    first_clean_from_bronze(
        input_bucket=args.input_bucket,
        input_key=args.input_key,
        output_bucket=args.output_bucket,
        output_key=args.output_key,
    )


if __name__ == "__main__":
    main()
