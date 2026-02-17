#!/usr/bin/env python3
import os
import argparse
from pathlib import Path
import boto3
from botocore.client import Config


def parse_args():
    p = argparse.ArgumentParser(description="Upload a local file to MinIO (S3).")
    p.add_argument("--local-path", required=True, help="Local file path to upload")
    p.add_argument("--bucket", default=os.getenv("MINIO_BUCKET_BRONZE", "bronze"), help="Target bucket")
    p.add_argument("--key", default=None, help="Object key in bucket (e.g., bronze/canada.jsonl)")
    return p.parse_args()


def main():
    args = parse_args()
    local_path = Path(args.local_path)

    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    endpoint = os.environ["MINIO_ENDPOINT"]          # ex: minio:9000
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    scheme = "https" if secure else "http"
    endpoint_url = f"{scheme}://{endpoint}"

    key = args.key or local_path.name  # default = filename

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

    # Create bucket if missing (safe)
    existing = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    if args.bucket not in existing:
        s3.create_bucket(Bucket=args.bucket)

    s3.upload_file(str(local_path), args.bucket, key)
    print(f"Uploaded: {local_path} -> s3://{args.bucket}/{key} (endpoint={endpoint_url})")


if __name__ == "__main__":
    main()
