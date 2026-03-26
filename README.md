# OpenFoodFacts Data Platform (MIG8110)

## Plateforme data OpenFoodFacts Canada avec pipeline ETL, entreposage objet et exploration Streamlit

Ce projet met en place une chaîne de traitement de données autour des exports OpenFoodFacts Canada:

- extraction des exports officiels OpenFoodFacts
- dépôt des données brutes dans MinIO
- transformation et normalisation en couche Silver
- chargement dans PostgreSQL
- exploration et administration via une application Streamlit

L'architecture est orchestrée avec Docker Compose et Airflow. La couche Silver est maintenue au format `Parquet`.

## 1. Objectifs

- Extraire les produits OpenFoodFacts Canada depuis les exports officiels
- Contrôler la qualité minimale des données avant ingestion
- Normaliser certains champs métier, notamment les catégories
- Charger un schéma PostgreSQL normalisé
- Améliorer les performances de consultation avec des index SQL
- Offrir une interface Streamlit pour la recherche, l'analyse et la comparaison de produits

## 2. Architecture Technique

Tous les composants sont définis dans `docker-compose.yml`.

Services principaux:

- `postgres` : base métier PostgreSQL
- `airflow-postgres` : base de métadonnées Airflow
- `minio` et `minio-init` : stockage objet S3-compatible et initialisation des buckets
- `airflow-webserver`, `airflow-scheduler`, `airflow-init` : orchestration ETL
- `streamlit-app` : interface utilisateur principale
- `adminer` : exploration de la base
- `jupyter` : exploration et prototypage

Vue simplifiée:

```text
OpenFoodFacts Official Exports
      |
      v
Airflow DAG (extract -> upload -> transform -> load)
      |                         |
      |                         +--> MinIO silver (Parquet)
      +--> MinIO bronze (JSONL)
                                |
                                v
                          PostgreSQL (schéma normalisé + index)
                                |
                                v
                      Streamlit (dashboard, insights, admin)
```

## 3. Architecture Data

### Bronze

- Données brutes issues du dump complet ou des delta exports
- Format: `JSONL`
- Bucket MinIO: `bronze`
- Scripts principaux:
  - `dags/scripts/extract_off_exports.py`
  - `dags/scripts/upload_bronze_to_minio.py`

### Silver

- Nettoyage, harmonisation et enrichissement des champs
- Normalisation pilotée par `config/normalization_rules.yml`
- Format conservé: `Parquet`
- Bucket MinIO: `silver`
- Script principal:
  - `dags/scripts/transform_to_silver.py`

### Chargement PostgreSQL

- La sortie Silver est chargée dans PostgreSQL
- Le schéma relationnel est créé si nécessaire avant chargement
- L'historique des imports est stocké dans `etl_import_history`
- Des index sont créés pour accélérer les recherches et certains usages analytiques
- Fichiers principaux:
  - `dags/scripts/load_to_postgres.py`
  - `dags/sql/create_tables.sql`
  - `dags/sql/explain_indexes.sql`

## 4. Pipeline Airflow

Le DAG principal est `openfood_pipeline_canada`.

Ordre des tâches:

1. `extract_products`
2. `upload_to_minio`
3. `transform_to_silver`
4. `load_to_postgres`

Planification actuelle:

- `timedelta(days=14)`
- `catchup=False`

Stratégie d'ingestion:

- premier chargement: dump complet OpenFoodFacts
- chargements suivants: delta exports non encore importés
- rafraîchissement complet périodique pour couvrir les suppressions côté source

Fichier DAG:

- `dags/openfood_pipeline_dag.py`

## 5. Base PostgreSQL

Le schéma SQL couvre les entités principales du domaine produit et les tables d'association nécessaires.

Le chargement alimente notamment:

- `produit`
- `valeurs_nutritionnelles`
- `categorie`
- `ingredient`
- `marque`
- `allergene`
- `label`
- `pays`
- `etl_import_history`

Les index créés automatiquement sont les suivants:

- `idx_produit_nom`
- `idx_categorie_nom`
- `idx_ingredient_nom`
- `idx_allergene_nom`
- `idx_label_nom`
- `idx_marque_nom`
- `idx_pays_nom`
- `idx_etl_import_history_imported_at`
- `idx_etl_import_history_type_end_ts` 

## 6. Application Streamlit

Point d'entrée:

- `streamlit_app/main.py`

Fonctionnalités disponibles:

- recherche par nom de produit
- filtre par catégorie principale
- recherche libre dans les catégories détaillées
- filtre NutriScore
- filtre sur le sucre
- tri par NutriScore, sucre ou sel
- page de détail produit
- page de tendances
- comparateur de produits
- profil santé avec recommandations personnalisées
- module d'administration CRUD

## 7. Prérequis

- Docker et Docker Compose
- Git

## 8. Démarrage Rapide

Depuis la racine du projet:

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Une fois la stack démarrée:

1. Ouvrir Airflow
2. Vérifier que le DAG `openfood_pipeline_canada` est visible
3. Lancer un run manuel si nécessaire
4. Ouvrir Streamlit pour consulter les données chargées

## 9. Accès aux Services

- Streamlit: http://localhost:8501
- Airflow: http://localhost:8080 `admin` / `admin123`
- Adminer: http://localhost:8081
- MinIO API: http://localhost:9000
- MinIO Console: http://localhost:9001
- JupyterLab: http://localhost:8888

Identifiants par défaut utiles:

- MinIO: `minioadmin` / `minioadmin123`
- Jupyter token: `openfood2024`
- Admin Streamlit: `admin` / `admin123` si `ADMIN_USER` et `ADMIN_PASSWORD` ne sont pas définis

## 10. État Attendu du Projet

- Airflow démarre et expose le DAG `openfood_pipeline_canada`
- MinIO contient les buckets `bronze`, `silver` et `gold` initialisés
- la couche `silver` est stockée en `Parquet`
- PostgreSQL contient les tables normalisées et `etl_import_history`
- les index SQL sont créés
- Streamlit permet la navigation entre dashboard, tendances, comparaison, profil santé et administration
