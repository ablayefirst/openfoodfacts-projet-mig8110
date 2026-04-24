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

def upload_to_minio(
    input_dir: str = "/opt/airflow/data",
    filename: str = "openfood_sample.jsonl",
    local_path: str = None,
    bucket: str = None,
    key: str = None,
    **_,
):
    """
    Airflow callable (no argparse).
    Upload local bronze file to MinIO.
    """
    if bucket is None:
        bucket = os.getenv("MINIO_BUCKET_BRONZE", "bronze")

    resolved_local_path = Path(local_path) if local_path else Path(input_dir) / "bronze" / filename
    if not resolved_local_path.exists():
        raise FileNotFoundError(f"Local file not found: {resolved_local_path}")

    endpoint = os.environ["MINIO_ENDPOINT"]          # ex: minio:9000
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    scheme = "https" if secure else "http"
    endpoint_url = f"{scheme}://{endpoint}"

    # Key par défaut dans MinIO
    if key is None:
        key = f"openfood/{resolved_local_path.name}"

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

    existing = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket)

    # Vérifie si le fichier est déjà présent dans MinIO avec la même taille
    local_size = resolved_local_path.stat().st_size
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
        remote_size = head["ContentLength"]
        if remote_size == local_size:
            print(
                f"Skipping upload: {resolved_local_path} already in s3://{bucket}/{key} "
                f"(taille identique: {local_size} octets)"
            )
            return {"bucket": bucket, "key": key, "local_path": str(resolved_local_path), "skipped": True}
    except s3.exceptions.NoSuchKey:
        pass
    except Exception:
        pass

    print(f"Upload en cours: {resolved_local_path} ({local_size / 1e9:.2f} GB) -> s3://{bucket}/{key}")
    s3.upload_file(str(resolved_local_path), bucket, key)
    print(f"Upload terminé: s3://{bucket}/{key}")

    return {"bucket": bucket, "key": key, "local_path": str(resolved_local_path), "skipped": False}


if __name__ == "__main__":
    main()
