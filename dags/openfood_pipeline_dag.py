"""
DAG Airflow pour le pipeline Open Food Facts Canada
Extraction → Upload MinIO → Transformation → Chargement
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# --- IMPORTANT ---
# Assure que /opt/airflow/dags est dans le PYTHONPATH
# (utile quand Airflow "ne voit" pas scripts/)
DAGS_PATH = os.path.dirname(os.path.abspath(__file__))
if DAGS_PATH not in sys.path:
    sys.path.insert(0, DAGS_PATH)

from scripts.extract_api_sample import extract_sample
from scripts.load_to_postgres import load_silver_to_postgres
from scripts.transform_to_silver import transform_to_silver
from scripts.upload_bronze_to_minio import upload_to_minio


default_args = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="openfood_pipeline_canada",
    default_args=default_args,
    description="Pipeline ETL Open Food Facts Canada",
    start_date=datetime(2024, 1, 1),
    schedule="0 2 * * *",   # Airflow >=2.4 préfère schedule= plutôt que schedule_interval=
    catchup=False,
    tags=["openfood", "canada", "etl"],
) as dag:

    # Chemin DATA commun (à adapter selon ton docker-compose volume)
    DATA_DIR = os.environ.get("DATA_DIR", "/opt/airflow/data")

    extract_task = PythonOperator(
        task_id="extract_products",
        python_callable=extract_sample,
        op_kwargs={
            "limit": int(os.getenv("SAMPLE_SIZE", 500)),
            "output_dir": DATA_DIR
        },
    )

    upload_task = PythonOperator(
        task_id="upload_to_minio",
        python_callable=upload_to_minio,
        op_kwargs={"input_dir": DATA_DIR},
    )

    transform_task = PythonOperator(
        task_id="transform_to_silver",
        python_callable=transform_to_silver,
        # transform_to_silver expects keys in MinIO (input_key, output_key)
        op_kwargs={
            "input_key": "openfood/openfood_sample.jsonl",
            "output_key": "openfood/openfood_sample.parquet",
            # optional: explicit bucket names (will fallback to env vars if omitted)
            "input_bucket": os.getenv("MINIO_BUCKET_BRONZE", "bronze"),
            "output_bucket": os.getenv("MINIO_BUCKET_SILVER", "silver"),
        },
    )

    load_task = PythonOperator(
        task_id="load_to_postgres",
        python_callable=load_silver_to_postgres,
        op_kwargs={
            "input_key": "openfood/openfood_sample.parquet",
            "input_bucket": os.getenv("MINIO_BUCKET_SILVER", "silver"),
            # optional: can also pass DB connection params here or rely on env vars
            "schema_sql_path": os.path.join(DAGS_PATH, "sql", "create_tables.sql"),
        },
    )

    extract_task >> upload_task >> transform_task >> load_task
