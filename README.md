# OpenFoodFacts Data Platform (MIG8110)

## Application web d'exploration et de comparaison nutritionnelle des produits alimentaires vendus au Canada

Plateforme data pour OpenFoodFacts Canada avec pipeline ETL Airflow, stockage MinIO, chargement PostgreSQL et interface Streamlit.
L'architecture est conteneurisee avec Docker Compose et structuree en couches Bronze/Silver (Gold reserve pour la suite).

## 1. Objectifs

- Extraire un echantillon de produits OpenFoodFacts
- Qualifier les donnees avant ingestion (filtres de completude)
- Standardiser les donnees (normalisation ingredients/categories)
- Charger un schema PostgreSQL normalise
- Permettre l'exploration metier via une application Streamlit

## 2. Architecture Technique (Docker)

Tous les composants sont definis dans `docker-compose.yml`.

Services principaux:
- `postgres` (PostgreSQL metier)
- `airflow-postgres` (base metadata Airflow)
- `minio` + `minio-init` (stockage S3-compatible + creation des buckets)
- `airflow-webserver`, `airflow-scheduler`, `airflow-init`
- `streamlit-app`
- `adminer`
- `jupyter`

Vue simplifiee:

```text
OpenFoodFacts API
      |
      v
Airflow DAG (extract -> upload -> transform -> load)
      |                         |
      |                         +--> MinIO silver (Parquet)
      +--> MinIO bronze (JSONL)
                                |
                                v
                          PostgreSQL (schema normalise)
                                |
                                v
                         Streamlit (Dashboard + Admin)
```

## 3. Architecture Data (Bronze / Silver / Gold)

### Bronze
- Source brute extraite depuis OpenFoodFacts
- Format: `JSONL`
- Emplacement MinIO: bucket `bronze`
- Script: `dags/scripts/extract_api_sample.py` puis `upload_bronze_to_minio.py`

### Silver
- Transformation/nettoyage + harmonisation des champs
- Normalisation via regles YAML: `config/normalization_rules.yml`
- Format: `Parquet`
- Emplacement MinIO: bucket `silver`
- Script: `dags/scripts/transform_to_silver.py`

### Gold
- Bucket reserve pour une couche metier enrichie (non alimentee pour l'instant)
- Le pipeline actuel charge la sortie Silver directement dans PostgreSQL
- Creation schema via SQL avant chargement
- Script: `dags/scripts/load_to_postgres.py`
- SQL schema: `dags/sql/create_tables.sql`

## 4. Pipeline Airflow

DAG: `openfood_pipeline_canada`

Ordre des taches:
1. `extract_products`
2. `upload_to_minio`
3. `transform_to_silver`
4. `load_to_postgres`

Planification:
- cron: `0 2 * * *`
- `catchup=False`

Fichier DAG:
- `dags/openfood_pipeline_dag.py`

## 5. Application Streamlit

Point d'entree:
- `streamlit_app/main.py`

Fonctionnalites:
- Dashboard nutrition (recherche, filtres, tri)
- Filtre categorie principale et categorie detaillee
- Visualisation de produits + details
- Module Admin integre (CRUD produits et relations)

Composants:
- `streamlit_app/main.py` (dashboard)
- `streamlit_app/admin.py` (admin)
- `streamlit_app/pages/01_detail_produit.py`
- `streamlit_app/pages/02_insights.py`

## 6. Prerequis

- Docker + Docker Compose
- Git

## 7. Demarrage Rapide

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

## 8. Acces aux Services

- Streamlit: http://localhost:8501
- Airflow: http://localhost:8080 (admin / admin123)
- Adminer: http://localhost:8081
- MinIO Console: http://localhost:9001 (minioadmin / minioadmin123)
- JupyterLab: http://localhost:8888 (token: openfood2024)

## 9. Variables d'Environnement Importantes

Configurer dans `.env` (a partir de `.env.example`):
- PostgreSQL metier: `POSTGRES_*`
- Airflow metadata DB: `AIRFLOW_DB*`
- MinIO: `MINIO_*`
- Source OpenFoodFacts: `OPENFOOD_API_URL`, `OPENFOOD_COUNTRY`, `SAMPLE_SIZE`
- Airflow core/webserver: `AIRFLOW__*`

## 10. Lancer et Controler le Pipeline

Option A (UI Airflow):
1. Ouvrir Airflow
2. Activer le DAG `openfood_pipeline_canada`
3. Lancer un run manuel

Option B (scheduler):
- Laisser Airflow executer selon le cron planifie

Verifier les sorties:
- Buckets MinIO `bronze` et `silver`
- Tables PostgreSQL alimentees
- Donnees visibles dans Streamlit

## 11. Arborescence Recommandee a Connaitre

- `docker-compose.yml`
- `dags/openfood_pipeline_dag.py`
- `dags/scripts/extract_api_sample.py`
- `dags/scripts/upload_bronze_to_minio.py`
- `dags/scripts/transform_to_silver.py`
- `dags/scripts/load_to_postgres.py`
- `config/normalization_rules.yml`
- `dags/sql/create_tables.sql`
- `streamlit_app/main.py`
- `streamlit_app/admin.py`

## 12. Troubleshooting

Verifier l'etat:
```bash
docker compose ps
```

Suivre les logs:
```bash
docker compose logs -f airflow-webserver airflow-scheduler streamlit-app
```

Redemarrer un service:
```bash
docker compose restart <service>
```

Arreter la stack:
```bash
docker compose down
```

## 13. Etat Attendu du Livrable

- Airflow demarre et expose le DAG `openfood_pipeline_canada`
- MinIO contient les buckets `bronze`, `silver` (`gold` peut etre vide pour l'instant)
- PostgreSQL contient les tables normalisees et les donnees chargees
- Streamlit permet la navigation Dashboard/Admin.
