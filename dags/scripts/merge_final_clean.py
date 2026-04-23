#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import tempfile

import pandas as pd
import pyarrow.parquet as pq

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from transform_to_silver import (
    normalize_code,
    should_replace_duplicate,
    write_empty_parquet,
    write_rows_chunk,
)
from transform_to_silver import get_s3_client


def parse_args():
    parser = argparse.ArgumentParser(description="Merge file1_good and recovered into final clean parquet.")
    parser.add_argument("--input-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    parser.add_argument("--good-key", required=True)
    parser.add_argument("--recovered-key", required=True)
    parser.add_argument("--output-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    parser.add_argument("--output-key", required=True)
    return parser.parse_args()


def load_parquet_object(s3, bucket: str, key: str) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_file:
        temp_path = tmp_file.name
    try:
        s3.download_file(bucket, key, temp_path)
        return pq.read_table(temp_path).to_pandas()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def merge_final_clean(
    good_key: str,
    recovered_key: str,
    output_key: str,
    input_bucket: str | None = None,
    output_bucket: str | None = None,
    **_,
):
    if input_bucket is None:
        input_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")
    if output_bucket is None:
        output_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")

    s3 = get_s3_client()
    good_df = load_parquet_object(s3, input_bucket, good_key)
    recovered_df = load_parquet_object(s3, input_bucket, recovered_key)

    merged_df = pd.concat([good_df, recovered_df], ignore_index=True)
    records = merged_df.to_dict(orient="records")

    deduped: dict[str, dict[str, object]] = {}
    duplicates_seen = 0
    duplicates_replaced = 0

    for row in records:
        code = normalize_code(row.get("code"))
        if code is None:
            continue
        existing = deduped.get(code)
        if existing is None:
            deduped[code] = row
            continue
        duplicates_seen += 1
        if should_replace_duplicate(existing, row):
            deduped[code] = row
            duplicates_replaced += 1

    final_rows = list(deduped.values())

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_file:
        final_path = tmp_file.name

    writer = None
    try:
        if not final_rows:
            write_empty_parquet(final_path)
        else:
            writer = write_rows_chunk(writer, final_rows, final_path)
        if writer is not None:
            writer.close()
            writer = None
        s3.upload_file(final_path, output_bucket, output_key)
    finally:
        if writer is not None:
            writer.close()
        if os.path.exists(final_path):
            os.remove(final_path)

    print(
        "Merge summary: "
        f"good_rows={len(good_df)}, recovered_rows={len(recovered_df)}, "
        f"final_rows={len(final_rows)}, duplicates_seen={duplicates_seen}, "
        f"duplicates_replaced={duplicates_replaced}"
    )
    print(f"Uploaded final clean parquet to s3://{output_bucket}/{output_key}")
    return {
        "final_key": output_key,
        "rows_good_input": len(good_df),
        "rows_recovered_input": len(recovered_df),
        "rows_final": len(final_rows),
        "duplicates_seen": duplicates_seen,
        "duplicates_replaced": duplicates_replaced,
    }


def main():
    args = parse_args()
    merge_final_clean(
        input_bucket=args.input_bucket,
        good_key=args.good_key,
        recovered_key=args.recovered_key,
        output_bucket=args.output_bucket,
        output_key=args.output_key,
    )


if __name__ == "__main__":
    main()
