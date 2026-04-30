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
    apply_validated_product_correction,
    apply_validated_category_suggestion,
    build_row,
    evaluate_final_contract,
    get_s3_client,
    infer_import_type,
    iter_json_lines,
    load_validated_category_suggestions,
    load_normalization_rules,
    load_validated_manual_product_submissions,
    load_validated_product_corrections,
    normalize_code,
    resolve_rejected_product_reviews,
    update_category_suggestion_status,
    upsert_rejected_product_reviews,
    write_empty_parquet,
    write_rows_chunk,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Second cleaning pass from file2_bad JSONL.")
    parser.add_argument("--input-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    parser.add_argument("--input-key", required=True)
    parser.add_argument("--output-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    parser.add_argument("--output-key", required=True, help="Final silver parquet key used as naming base.")
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
        "category_suggestions_loaded": 0,
        "category_suggestions_applied": 0,
        "manual_product_corrections_loaded": 0,
        "manual_product_corrections_applied": 0,
        "suggested_primary_category_overrides": 0,
    }


def second_clean_from_bad(
    input_key: str,
    output_key: str,
    input_bucket: str | None = None,
    output_bucket: str | None = None,
    chunk_size: int = 5000,
    **_,
):
    if input_bucket is None:
        input_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")
    if output_bucket is None:
        output_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")

    keys = derive_recovery_keys(output_key)
    s3 = get_s3_client()
    rules, rules_source = load_normalization_rules()
    category_suggestions = load_validated_category_suggestions()
    product_corrections = load_validated_product_corrections()
    manual_submissions = load_validated_manual_product_submissions()
    obj = s3.get_object(Bucket=input_bucket, Key=input_key)
    source_run_id = os.getenv("AIRFLOW_CTX_DAG_RUN_ID")
    import_type = infer_import_type()

    stats = init_second_clean_stats()
    stats["category_suggestions_loaded"] = len(category_suggestions)
    stats["manual_product_corrections_loaded"] = len(product_corrections)
    stats["manual_product_submissions_loaded"] = len(manual_submissions)
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
        "manual_product_corrections_applied": 0,
        "suggested_primary_category_overrides": 0,
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
    rejected_reviews: list[dict[str, object]] = []
    recovered_codes: set[str] = set()
    rejected_suggested_codes: set[str] = set()
    recovered_suggested_codes: set[str] = set()
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
                code = normalize_code(product.get("code"))
                product_after_manual_correction, manual_correction_applied = apply_validated_product_correction(
                    product,
                    product_corrections.get(code) if code is not None else None,
                    stats=transform_stats,
                )
                suggestion = category_suggestions.get(code) if code is not None else None
                corrected_product, suggestion_applied = apply_validated_category_suggestion(
                    product_after_manual_correction,
                    suggestion,
                    stats=transform_stats,
                )
                row = build_row(
                    corrected_product,
                    stats=transform_stats,
                    rules=rules,
                    recovery_mode=True,
                    category_suggestion=suggestion,
                )
                issues = evaluate_final_contract(row, recovery_mode=True)

                if issues:
                    rejected_product = dict(corrected_product)
                    rejected_product["_quality_contract_issues"] = issues
                    reject_handle.write(json.dumps(rejected_product, ensure_ascii=False) + "\n")
                    stats["rows_rejected"] += 1
                    rejected_reviews.append(
                        {
                            "code_produit": row.get("code") or product.get("code"),
                            "product_name": row.get("product_name") or product.get("product_name"),
                            "brands": row.get("brands") or product.get("brands"),
                            "raw_payload": rejected_product,
                            "quality_issues": issues,
                            "review_status": "needs_review" if suggestion_applied else "pending",
                        }
                    )
                    if suggestion_applied and row.get("code"):
                        rejected_suggested_codes.add(str(row["code"]))
                    for issue in issues:
                        stats[issue] = stats.get(issue, 0) + 1
                    continue

                rows_batch.append({column: row.get(column) for column in OUTPUT_COLUMNS})
                stats["rows_recovered"] += 1
                if row.get("code"):
                    recovered_codes.add(str(row["code"]))
                    if suggestion_applied:
                        recovered_suggested_codes.add(str(row["code"]))
                    if manual_correction_applied:
                        recovered_suggested_codes.add(str(row["code"]))
                if len(rows_batch) >= chunk_size:
                    writer = write_rows_chunk(writer, rows_batch, recovered_path)
                    rows_batch = []

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
        upsert_rejected_product_reviews(
            rejected_reviews,
            source_task="second_clean_from_bad",
            source_run_id=source_run_id,
            import_type=import_type,
            rules=rules,
        )
        resolve_rejected_product_reviews(recovered_codes)
        update_category_suggestion_status(recovered_suggested_codes, "applied")
        update_category_suggestion_status(rejected_suggested_codes, "rejected")
        stats["rules_loaded"] = 0 if rules_source == "defaults" else 1
        stats.update(transform_stats)

        print(
            "Second cleaning summary: "
            f"input={stats['rows_input']}, recovered={stats['rows_recovered']}, rejected={stats['rows_rejected']}, "
            f"invalid_json={stats['invalid_json_lines']}, empty_lines={stats['empty_lines']}"
        )
        print(
            f"Uploaded second-clean outputs to s3://{output_bucket}/{keys['recovered_key']} "
            f"and s3://{output_bucket}/{keys['reject_key']}"
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
