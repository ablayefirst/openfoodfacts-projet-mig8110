#!/usr/bin/env python3
import os
import json
import argparse
from io import BytesIO
import pandas as pd
import boto3
from botocore.client import Config


def parse_args():
    p = argparse.ArgumentParser(description="Transform Bronze JSONL in MinIO to Silver Parquet in MinIO.")
    p.add_argument("--input-bucket", default=os.getenv("MINIO_BUCKET_BRONZE", "bronze"))
    p.add_argument("--input-key", required=True, help="Key of the JSONL object in bronze bucket")
    p.add_argument("--output-bucket", default=os.getenv("MINIO_BUCKET_SILVER", "silver"))
    p.add_argument("--output-key", required=True, help="Key of the Parquet object in silver bucket")
    return p.parse_args()


def get_s3_client():
    endpoint = os.environ["MINIO_ENDPOINT"].strip()
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        endpoint_url = endpoint
    else:
        scheme = "https" if secure else "http"
        endpoint_url = f"{scheme}://{endpoint}"

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def main():
    args = parse_args()
    s3 = get_s3_client()

    # 1) Download JSONL from MinIO
    obj = s3.get_object(Bucket=args.input_bucket, Key=args.input_key)
    body = obj["Body"].read().decode("utf-8", errors="replace")

    products = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        products.append(json.loads(line))

    # 2) Minimal flattening (simple “products_sample” schema)
    rows = []
    for p in products:
        nutr = p.get("nutriments") or {}

        # Helpers: ensure list fields are lists
        labels_tags = p.get("labels_tags") or []
        if not isinstance(labels_tags, list):
            labels_tags = []

        categories_tags = p.get("categories_tags") or []
        if not isinstance(categories_tags, list):
            categories_tags = []

        countries_tags = p.get("countries_tags") or []
        if not isinstance(countries_tags, list):
            countries_tags = []

        allergens_tags = p.get("allergens_tags") or []
        if not isinstance(allergens_tags, list):
            allergens_tags = []

        rows.append({
            # Identity
            "code": p.get("code"),

            # Text fields
            "product_name": p.get("product_name") or p.get("product_name_fr"),
            "brands": p.get("brands"),

            # Labels & categories
            "labels_tags": labels_tags,                 # list[str]
            "categories": p.get("categories"),
            "categories_tags": categories_tags,         # list[str]

            # Scores / groups
            "nutriscore_grade": p.get("nutriscore_grade"),
            "nutriscore_score": p.get("nutriscore_score"),
            "nova_group": p.get("nova_group"),

            # Nutriments (flattened)
            "energy_100g": nutr.get("energy_100g"),
            "energy_kcal_100g": nutr.get("energy-kcal_100g"),
            "sugars_100g": nutr.get("sugars_100g"),
            "fat_100g": nutr.get("fat_100g"),
            "saturated_fat_100g": nutr.get("saturated-fat_100g"),
            "salt_100g": nutr.get("salt_100g"),
            "fiber_100g": nutr.get("fiber_100g"),
            "proteins_100g": nutr.get("proteins_100g"),
            "carbohydrates_100g": nutr.get("carbohydrates_100g"),

            # Ingredients
            "ingredients_text": p.get("ingredients_text") or p.get("ingredients_text_fr"),
            "allergens_tags": allergens_tags,

            # Countries
            "countries": p.get("countries"),
            "countries_tags": countries_tags,           # list[str]

            # Images
            "image_small_url": p.get("image_small_url"),
            "image_url": p.get("image_url"),
        })

    df = pd.DataFrame(rows)

    # 3) Write Parquet to memory
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)

    # 4) Upload to MinIO (silver)
    s3.put_object(Bucket=args.output_bucket, Key=args.output_key, Body=buf.getvalue())

    print(f"Transformed {len(df)} rows")
    print(f"Uploaded Parquet to s3://{args.output_bucket}/{args.output_key}")

def transform_to_silver(
    input_key: str,
    output_key: str,
    input_bucket: str = None,
    output_bucket: str = None,
    **_,
):
    """
    Airflow callable (no argparse).
    Reads JSONL from MinIO (bronze) and writes Parquet to MinIO (silver).
    """
    if input_bucket is None:
        input_bucket = os.getenv("MINIO_BUCKET_BRONZE", "bronze")
    if output_bucket is None:
        output_bucket = os.getenv("MINIO_BUCKET_SILVER", "silver")

    s3 = get_s3_client()

    obj = s3.get_object(Bucket=input_bucket, Key=input_key)
    body = obj["Body"].read().decode("utf-8", errors="replace")

    products = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        products.append(json.loads(line))

    rows = []
    for p in products:
        nutr = p.get("nutriments") or {}

        labels_tags = p.get("labels_tags") or []
        if not isinstance(labels_tags, list):
            labels_tags = []

        categories_tags = p.get("categories_tags") or []
        if not isinstance(categories_tags, list):
            categories_tags = []

        countries_tags = p.get("countries_tags") or []
        if not isinstance(countries_tags, list):
            countries_tags = []

        rows.append({
            "code": p.get("code"),
            "product_name": p.get("product_name") or p.get("product_name_fr"),
            "brands": p.get("brands"),
            "labels_tags": labels_tags,
            "categories": p.get("categories"),
            "categories_tags": categories_tags,
            "nutriscore_grade": p.get("nutriscore_grade"),
            "nutriscore_score": p.get("nutriscore_score"),
            "nova_group": p.get("nova_group"),
            "energy_100g": nutr.get("energy_100g"),
            "energy_kcal_100g": nutr.get("energy-kcal_100g"),
            "sugars_100g": nutr.get("sugars_100g"),
            "fat_100g": nutr.get("fat_100g"),
            "saturated_fat_100g": nutr.get("saturated-fat_100g"),
            "salt_100g": nutr.get("salt_100g"),
            "fiber_100g": nutr.get("fiber_100g"),
            "proteins_100g": nutr.get("proteins_100g"),
            "carbohydrates_100g": nutr.get("carbohydrates_100g"),
            "ingredients_text": p.get("ingredients_text") or p.get("ingredients_text_fr"),
            "allergens_tags": p.get("allergens_tags") if isinstance(p.get("allergens_tags"), list) else [],
            "countries": p.get("countries"),
            "countries_tags": countries_tags,
            "image_small_url": p.get("image_small_url"),
            "image_url": p.get("image_url"),
        })

    df = pd.DataFrame(rows)

    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)

    s3.put_object(Bucket=output_bucket, Key=output_key, Body=buf.getvalue())

    print(f"Transformed {len(df)} rows")
    print(f"Uploaded Parquet to s3://{output_bucket}/{output_key}")

if __name__ == "__main__":
    main()
