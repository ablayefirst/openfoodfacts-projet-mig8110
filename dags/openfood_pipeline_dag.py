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
DAGS_PATH = os.path.dirname(os.path.abspath(__file__))
if DAGS_PATH not in sys.path:
    sys.path.insert(0, DAGS_PATH)

# IMPORTS
from scripts.extract_off_exports import extract_official_exports
from scripts.first_clean_from_bronze import first_clean_from_bronze
from scripts.build_similarity import build_similarity_recommendations
from scripts.load_to_postgres import load_silver_to_postgres
from scripts.merge_final_clean import merge_final_clean
from scripts.second_clean_from_bad import second_clean_from_bad
from scripts.upload_bronze_to_minio import upload_to_minio


# =========================
# DEFAULT ARGS
# =========================
default_args = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


# =========================
# DAG
# =========================
with DAG(
    dag_id="openfood_pipeline_canada",
    default_args=default_args,
    description="Pipeline ETL Open Food Facts Canada (LOCAL FULL DUMP optimisé)",
    start_date=datetime(2024, 1, 1),
    schedule=timedelta(days=14),
    catchup=False,
    tags=["openfood", "canada", "etl"],
) as dag:

    DATA_DIR = os.environ.get("DATA_DIR", "/opt/airflow/data")

    # =========================
    # 🔥 EXTRACT CORRIGÉ
    # =========================
    extract_task = PythonOperator(
        task_id="extract_products",
        python_callable=extract_official_exports,
        op_kwargs={
            # 🔥 IMPORTANT (corrigé)
            "source_mode": os.getenv("OPENFOOD_SOURCE_MODE", "local"),

            # config pipeline
            "output_dir": DATA_DIR,
            "country": os.getenv("OPENFOOD_COUNTRY", "united states").lower(),
            "min_core_nutrients": int(os.getenv("OPENFOOD_MIN_CORE_NUTRIENTS", "1")),
            "max_rows": int(os.getenv("OPENFOOD_MAX_ROWS", "10")),
        },
    )

    # =========================
    # UPLOAD
    # =========================
    upload_task = PythonOperator(
        task_id="upload_to_minio",
        python_callable=upload_to_minio,
        op_kwargs={
            "local_path": "{{ ti.xcom_pull(task_ids='extract_products')['local_path'] }}",
            "bucket": os.getenv("MINIO_BUCKET_BRONZE", "bronze"),
            "key": "{{ ti.xcom_pull(task_ids='extract_products')['bronze_key'] }}",
        },
    )

    # =========================
    # CLEAN 1
    # =========================
    first_clean_task = PythonOperator(
        task_id="first_clean_from_bronze",
        python_callable=first_clean_from_bronze,
        op_kwargs={
            "input_key": "{{ ti.xcom_pull(task_ids='extract_products')['bronze_key'] }}",
            "output_key": "{{ ti.xcom_pull(task_ids='extract_products')['silver_key'] }}",
            "input_bucket": os.getenv("MINIO_BUCKET_BRONZE", "bronze"),
            "output_bucket": os.getenv("MINIO_BUCKET_SILVER", "silver"),
        },
    )

    # =========================
    # CLEAN 2
    # =========================
    second_clean_task = PythonOperator(
        task_id="second_clean_from_bad",
        python_callable=second_clean_from_bad,
        op_kwargs={
            "input_key": "{{ ti.xcom_pull(task_ids='first_clean_from_bronze')['bad_key'] }}",
            "output_key": "{{ ti.xcom_pull(task_ids='extract_products')['silver_key'] }}",
            "input_bucket": os.getenv("MINIO_BUCKET_SILVER", "silver"),
            "output_bucket": os.getenv("MINIO_BUCKET_SILVER", "silver"),
        },
    )

    # =========================
    # MERGE
    # =========================
    merge_task = PythonOperator(
        task_id="merge_final_clean",
        python_callable=merge_final_clean,
        op_kwargs={
            "good_key": "{{ ti.xcom_pull(task_ids='first_clean_from_bronze')['good_key'] }}",
            "recovered_key": "{{ ti.xcom_pull(task_ids='second_clean_from_bad')['recovered_key'] }}",
            "output_key": "{{ ti.xcom_pull(task_ids='extract_products')['silver_key'] }}",
            "input_bucket": os.getenv("MINIO_BUCKET_SILVER", "silver"),
            "output_bucket": os.getenv("MINIO_BUCKET_SILVER", "silver"),
        },
    )

    # =========================
    # LOAD
    # =========================
    load_task = PythonOperator(
        task_id="load_to_postgres",
        python_callable=load_silver_to_postgres,
        op_kwargs={
            "input_key": "{{ ti.xcom_pull(task_ids='merge_final_clean')['final_key'] }}",
            "input_bucket": os.getenv("MINIO_BUCKET_SILVER", "silver"),
            "import_type": "{{ ti.xcom_pull(task_ids='extract_products')['import_type'] }}",
            "bronze_key": "{{ ti.xcom_pull(task_ids='extract_products')['bronze_key'] }}",
            "schema_sql_path": os.path.join(DAGS_PATH, "sql", "create_tables.sql"),
        },
    )

    # =========================
    # RECO
    # =========================
    build_similarity_task = PythonOperator(
        task_id="build_similarity_recommendations",
        python_callable=build_similarity_recommendations,
    )

    # =========================
    # PIPELINE FLOW
    # =========================
    extract_task >> upload_task >> first_clean_task >> second_clean_task >> merge_task >> load_task >> build_similarity_task