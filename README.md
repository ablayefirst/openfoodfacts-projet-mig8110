# OpenFoodFacts Data Platform (MIG8110)

## Plateforme data OpenFoodFacts Canada avec pipeline ETL, entreposage objet et exploration Streamlit

Ce projet met en place une chaîne de traitement de données autour des exports OpenFoodFacts Canada:

- extraction des exports officiels OpenFoodFacts
- prise en charge optionnelle d'une source locale JSONL pour le bootstrap
- dépôt des données brutes dans MinIO
- nettoyage en deux étapes et normalisation en couche Silver
- chargement dans PostgreSQL
- exploration et administration via une application Streamlit

L'architecture est orchestrée avec Docker Compose et Airflow. La couche Silver est maintenue au format `Parquet`.

## 1. Objectifs

- Extraire les produits OpenFoodFacts Canada depuis les exports officiels ou une source locale
- Contrôler la qualité minimale des données avant ingestion
- Normaliser certains champs métier, notamment les catégories, le NutriScore et les quantités
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
Source de données
      |
      +--> Exports officiels OpenFoodFacts
      |
      |     +--> Full dump (full)
      |     +--> Delta exports (delta)
      |
      +--> Fichier local JSONL (mode local)
      |
      v
Airflow DAG
extract -> upload -> first_clean -> second_clean -> merge -> load
      |
      +--> MinIO bronze (JSONL brut)
      |
      +--> MinIO silver
            +--> first/..._file1_good.parquet
            +--> first/..._file2_bad.jsonl
            +--> second/..._recovered.parquet
            +--> second/..._reject.jsonl
            +--> final parquet fusionné
      |
      v
PostgreSQL (schéma normalisé + index)
      |
      v
Streamlit (dashboard, insights, admin)
```

## 3. Architecture Data

### Bronze

- Données brutes issues d'un full, d'un delta ou d'un fichier local
- Format: `JSONL`
- Bucket MinIO: `bronze`
- Scripts principaux:
  - `dags/scripts/extract_off_exports.py`
  - `dags/scripts/upload_bronze_to_minio.py`

### Silver

- Nettoyage, récupération, harmonisation et enrichissement des champs
- Normalisation pilotée par `config/normalization_rules.yml`
- Format conservé: `Parquet`
- Bucket MinIO: `silver`
- Scripts principaux:
  - `dags/scripts/transform_to_silver.py`
  - `dags/scripts/first_clean_from_bronze.py`
  - `dags/scripts/second_clean_from_bad.py`
  - `dags/scripts/merge_final_clean.py`

Le pipeline Silver produit maintenant quatre sorties intermédiaires:

- `file1_good.parquet`: lignes conformes dès le premier nettoyage
- `file2_bad.jsonl`: lignes échouant au premier contrat qualité mais encore récupérables
- `recovered.parquet`: lignes sauvées au second nettoyage
- `reject.jsonl`: lignes toujours invalides après la seconde tentative

Le fichier Silver final chargé dans PostgreSQL est la fusion dédupliquée de:

- `file1_good`
- `recovered`

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
3. `first_clean_from_bronze`
4. `second_clean_from_bad`
5. `merge_final_clean`
6. `load_to_postgres`

Planification actuelle:

- `timedelta(days=14)`
- `catchup=False`

Stratégie d'ingestion:

- premier chargement possible: dump complet OpenFoodFacts ou fichier local JSONL
- chargements incrémentaux: delta exports non encore importés
- rafraîchissement complet périodique pour couvrir les suppressions côté source

Modes de source pris en charge:

- `OPENFOOD_SOURCE_MODE=official`
  - utilise les exports OpenFoodFacts
  - avec `OPENFOOD_IMPORT_MODE=full`, `delta` ou `auto`
- `OPENFOOD_SOURCE_MODE=local`
  - utilise un fichier JSONL local défini par `OPENFOOD_LOCAL_FILE`
  - utile pour bootstrapper le projet à partir d'un export déjà disponible

Options utiles d'extraction:

- `OPENFOOD_FULL_MODE=direct|sample`
- `OPENFOOD_FULL_SAMPLE_SIZE`
- `OPENFOOD_FULL_SAMPLE_STRATEGY=first|random`
- `OPENFOOD_DELTA_MAX_FILES`

### Rôle détaillé des deux nettoyages

#### Premier nettoyage: `first_clean_from_bronze`

Cette étape lit le JSONL Bronze depuis MinIO et transforme chaque produit vers le schéma Silver cible.

Elle utilise:

- `build_row(..., recovery_mode=False)`
- `evaluate_final_contract(...)`

Son objectif est de faire un premier tri qualité:

- normaliser les champs principaux
- vérifier la présence et la cohérence des données importantes
- séparer les lignes directement exploitables des lignes encore douteuses

Résultats:

- `file1_good.parquet`
  - contient les lignes qui passent déjà le contrat qualité final
- `file2_bad.jsonl`
  - contient les lignes qui ont encore des problèmes mais qui méritent une seconde tentative

Exemples de contrôles appliqués à ce stade:

- qualité du nom produit
- présence et normalisation des catégories
- cohérence du NutriScore
- format de quantité
- cohérence énergétique ou sel/sodium selon les champs disponibles

#### Second nettoyage: `second_clean_from_bad`

Cette étape relit uniquement `file2_bad.jsonl`.

Elle applique la même logique métier générale, mais dans un mode plus tolérant:

- `build_row(..., recovery_mode=True)`
- `evaluate_final_contract(...)`

Le second nettoyage sert à récupérer les cas limites qui n'ont pas passé le premier filtre, par exemple:

- recherche du nom dans des champs alternatifs
- récupération plus large des catégories
- récupération de marques via variantes linguistiques
- réconciliation plus souple entre `nutriscore_grade` et `nutriscore_score`
- meilleure normalisation des quantités atypiques

Résultats:

- `recovered.parquet`
  - lignes sauvées au second passage
- `reject.jsonl`
  - lignes définitivement rejetées après la seconde tentative

Cette séparation permet de mieux contrôler la qualité des données:

- `good` = propre dès le départ
- `bad` = encore récupérable
- `recovered` = corrigé avec succès
- `reject` = non exploitable en l'état

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
3. Configurer si nécessaire le mode de source dans `.env`
4. Lancer un run manuel si nécessaire
5. Ouvrir Streamlit pour consulter les données chargées

Exemple pour utiliser un fichier local:

```env
OPENFOOD_SOURCE_MODE=local
OPENFOOD_LOCAL_FILE=data/bronze/openfood/local/openfood_canada_local.jsonl
```

Exemple pour utiliser la source officielle:

```env
OPENFOOD_SOURCE_MODE=official
OPENFOOD_IMPORT_MODE=auto
```

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
- la couche `silver` contient les sorties intermédiaires de nettoyage et le fichier final en `Parquet`
- PostgreSQL contient les tables normalisées et `etl_import_history`
- les index SQL sont créés
- Streamlit permet la navigation entre dashboard, tendances, comparaison, profil santé et administration
