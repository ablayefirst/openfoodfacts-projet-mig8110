# OpenFoodFacts Projet MIG8110

Projet de cours de type data platform pour exploiter des donnees OpenFoodFacts Canada:
- ingestion depuis l'API OpenFoodFacts
- stockage objet (MinIO)
- transformation en couche Silver
- chargement en base PostgreSQL
- visualisation et administration via Streamlit
- orchestration avec Apache Airflow

## 1. Architecture

Composants principaux:
- `postgres` : base metier OpenFood (`openfood_db`)
- `airflow-postgres` : base metadata Airflow
- `minio` + `minio-init` : stockage objets S3 compatible (bronze/silver/gold)
- `airflow-webserver`, `airflow-scheduler`, `airflow-init` : orchestration ETL
- `streamlit-app` : interface utilisateur et module admin
- `jupyter` : exploration notebooks
- `adminer` : interface SQL web

Tout est lance via `docker-compose.yml`.

## 2. Arborescence utile

- `dags/openfood_pipeline_dag.py` : DAG Airflow principal
- `dags/scripts/` : scripts ETL (extract, upload, transform, load)
- `dags/sql/create_tables.sql` : creation du schema metier
- `config/normalization_rules.yml` : regles de normalisation
- `streamlit_app/main.py` : dashboard Streamlit
- `streamlit_app/admin.py` : CRUD d'administration
- `database/schema/create_tables.sql` : script SQL de schema (reference)

## 3. Prerequis

- Docker + Docker Compose
- Git

## 4. Installation rapide (remise)

Depuis la racine du projet:

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Si un service ne demarre pas:

```bash
docker compose logs -f <service>
```

## 5. Acces aux services

- Streamlit: http://localhost:8501
- Airflow: http://localhost:8080  (admin / admin123)
- Adminer: http://localhost:8081
- MinIO Console: http://localhost:9001  (minioadmin / minioadmin123)
- JupyterLab: http://localhost:8888  (token: `openfood2024`)

## 6. Pipeline Airflow

DAG: `openfood_pipeline_canada`

Ordre des taches:
1. `extract_products` (`extract_api_sample.py`)
2. `upload_to_minio` (`upload_bronze_to_minio.py`)
3. `transform_to_silver` (`transform_to_silver.py`)
4. `load_to_postgres` (`load_to_postgres.py`)

Planification: tous les jours a 02:00 (`schedule="0 2 * * *"`).

Variables importantes (dans `.env`):
- `OPENFOOD_API_URL`, `OPENFOOD_COUNTRY`, `SAMPLE_SIZE`
- `MINIO_*`
- `POSTGRES_*`
- `AIRFLOW_*`

## 7. Application Streamlit

Fonctionnalites principales:
- recherche produit par nom
- filtre categorie principale
- filtre categories detaillees
- filtre NutriScore
- tri nutrition (NutriScore, sucre, sel)
- page detail produit
- module Admin (ajout/modification/suppression)

Identifiants admin Streamlit (par defaut):
- utilisateur: `admin`
- mot de passe: `admin123`

(Variables surchargeables via `ADMIN_USER` et `ADMIN_PASSWORD`.)

## 8. Lancement local sans Docker (optionnel)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app/main.py
```

Configurer au besoin les variables `POSTGRES_*` pour pointer vers la base.

## 9. Troubleshooting

- Verifier l'etat des conteneurs:
```bash
docker compose ps
```
- Suivre les logs Airflow:
```bash
docker compose logs -f airflow-webserver airflow-scheduler
```
- Suivre les logs Streamlit:
```bash
docker compose logs -f streamlit-app
```
- Reinitialiser proprement (attention: supprime les conteneurs):
```bash
docker compose down
```

## 10. Etat actuel attendu

En environnement Docker sain:
- Airflow est accessible et le DAG `openfood_pipeline_canada` est visible
- MinIO contient les buckets `bronze`, `silver`, `gold`
- PostgreSQL contient les tables metier OpenFood
- Streamlit affiche les produits et permet la navigation Dashboard/Admin
