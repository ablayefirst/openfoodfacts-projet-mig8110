# OpenFoodFacts Data Platform (MIG8110)

## Plateforme data OpenFoodFacts avec pipeline ETL, stockage objet, PostgreSQL, IA et Streamlit

Ce projet met en place une chaîne complète de traitement de données autour des exports OpenFoodFacts. Il transforme des données alimentaires brutes, hétérogènes et parfois incomplètes en une plateforme exploitable pour l'analyse, la comparaison et la recommandation de produits.

La plateforme couvre :

- extraction des exports officiels OpenFoodFacts ou chargement d'un fichier local JSONL
- dépôt des données brutes dans MinIO, zone Bronze
- nettoyage en deux passes et normalisation en zone Silver au format Parquet
- chargement dans PostgreSQL selon un schéma relationnel normalisé
- standardisation des ingrédients par clustering TF-IDF et DBSCAN, avec enrichissement LLM optionnel
- construction de recommandations produit via un moteur de similarité multimodal
- exploration, comparaison et administration via une application Streamlit multi-pages

L'architecture est orchestrée avec Docker Compose et Airflow.

## 1. Objectifs

- Extraire les produits OpenFoodFacts depuis les exports officiels ou une source locale
- Contrôler la qualité minimale des données avant ingestion
- Normaliser les champs métier : catégories, NutriScore, quantités, nutriments et ingrédients
- Charger un schéma PostgreSQL normalisé et indexé
- Standardiser les ingrédients à partir des variantes présentes dans les données
- Générer des recommandations de produits similaires ou plus sains
- Offrir une interface Streamlit pour la recherche, l'analyse, la comparaison et l'administration

## 2. Architecture Technique

Tous les composants sont définis dans `docker-compose.yml`.

Services principaux :

- `postgres` : base métier PostgreSQL
- `airflow-postgres` : base de métadonnées Airflow
- `minio` et `minio-init` : stockage objet S3-compatible et initialisation des buckets
- `airflow-webserver`, `airflow-scheduler`, `airflow-init` : orchestration ETL
- `streamlit-app` : interface utilisateur principale
- `adminer` : exploration de la base PostgreSQL
- `jupyter` : exploration et prototypage
- `build-similarity` : service éphémère pour recalculer les similarités si nécessaire

Vue simplifiée :

```text
Source de données
      |
      +--> Exports officiels OpenFoodFacts
      |     +--> Full dump
      |     +--> Delta exports
      |
      +--> Fichier local JSONL
      |
      v
Airflow DAG : openfood_pipeline_united_states
extract -> upload -> first_clean -> second_clean -> merge -> load
        -> standardize_ingredients -> build_similarity_recommendations
      |
      +--> MinIO bronze : JSONL brut
      |
      +--> MinIO silver : Parquet nettoyé
      |     +--> first/..._file1_good.parquet
      |     +--> first/..._file2_bad.jsonl
      |     +--> second/..._recovered.parquet
      |     +--> second/..._reject.jsonl
      |     +--> final parquet fusionné
      |
      v
PostgreSQL : schéma normalisé, index, historique, similarités
      |
      +--> ingredient_standardise + synonyme_ingredient
      +--> product_similarity
      |
      v
Streamlit : recherche, détails, insights, comparateur, favoris, admin
```

## 3. Architecture Data

### Bronze

- Données brutes issues d'un full dump, d'un delta export ou d'un fichier local
- Format : `JSONL`
- Bucket MinIO : `bronze`
- Scripts principaux :
  - `dags/scripts/extract_off_exports.py`
  - `dags/scripts/upload_bronze_to_minio.py`

### Silver

- Nettoyage, récupération, harmonisation et enrichissement des champs
- Normalisation pilotée par `config/normalization_rules.yml`
- Format : `Parquet`
- Bucket MinIO : `silver`
- Scripts principaux :
  - `dags/scripts/transform_to_silver.py`
  - `dags/scripts/first_clean_from_bronze.py`
  - `dags/scripts/second_clean_from_bad.py`
  - `dags/scripts/merge_final_clean.py`

Le pipeline Silver produit quatre sorties intermédiaires :

- `file1_good.parquet` : lignes conformes dès le premier nettoyage
- `file2_bad.jsonl` : lignes échouant au premier contrat qualité mais encore récupérables
- `recovered.parquet` : lignes sauvées au second nettoyage
- `reject.jsonl` : lignes définitivement invalides après la seconde tentative

Le fichier Silver final chargé dans PostgreSQL est la fusion dédupliquée de `file1_good` et `recovered`.

### PostgreSQL

- La sortie Silver est chargée dans PostgreSQL via `dags/scripts/load_to_postgres.py`
- Le schéma relationnel est créé ou mis à jour avec `dags/sql/create_tables.sql`
- L'historique des imports est stocké dans `etl_import_history`
- Des index sont créés pour accélérer les recherches et les analyses
- Le fichier `dags/sql/explain_indexes.sql` documente les index et leur rôle

## 4. Pipeline Airflow

Le DAG principal est `openfood_pipeline_united_states`.

Ordre des tâches :

1. `extract_products`
2. `upload_to_minio`
3. `first_clean_from_bronze`
4. `second_clean_from_bad`
5. `merge_final_clean`
6. `load_to_postgres`
7. `standardize_ingredients`
8. `build_similarity_recommendations`

Planification :

- `schedule=timedelta(days=14)`
- `catchup=False`
- `retries=1`

Stratégie d'ingestion :

- premier chargement : dump complet OpenFoodFacts ou fichier local JSONL
- chargements incrémentaux : delta exports non encore importés
- rafraîchissement complet périodique configurable avec `OPENFOOD_FULL_REFRESH_INTERVAL_DAYS`
- limite de lignes possible en développement avec `OPENFOOD_MAX_ROWS`

Modes de source pris en charge :

```env
OPENFOOD_SOURCE_MODE=official
OPENFOOD_IMPORT_MODE=full|delta|auto
```

```env
OPENFOOD_SOURCE_MODE=local
OPENFOOD_LOCAL_FILE=data/bronze/openfood/local/openfoodfacts-products.jsonl.gz
```

Options utiles d'extraction :

- `OPENFOOD_COUNTRY`
- `OPENFOOD_FULL_MODE=direct|sample`
- `OPENFOOD_FULL_SAMPLE_SIZE`
- `OPENFOOD_FULL_SAMPLE_STRATEGY=first|random`
- `OPENFOOD_DELTA_MAX_FILES`
- `OPENFOOD_MAX_ROWS`

### Nettoyage en deux passes

#### Premier nettoyage : `first_clean_from_bronze`

Cette étape lit le JSONL Bronze depuis MinIO et applique `build_row(..., recovery_mode=False)` suivi de `evaluate_final_contract(...)`.

Contrôles principaux :

- qualité du nom produit
- présence et normalisation des catégories
- cohérence du NutriScore
- format de quantité
- cohérence énergétique ou sel/sodium selon les champs disponibles

Résultats :

- `file1_good.parquet` : lignes qui passent directement le contrat qualité final
- `file2_bad.jsonl` : lignes à tenter de récupérer

#### Second nettoyage : `second_clean_from_bad`

Cette étape relit uniquement `file2_bad.jsonl` et applique `build_row(..., recovery_mode=True)`.

Le mode récupération est plus tolérant : noms alternatifs, catégories élargies, réconciliation NutriScore, marques via variantes linguistiques et quantités atypiques.

Résultats :

- `recovered.parquet` : lignes sauvées au second passage
- `reject.jsonl` : lignes définitivement rejetées

Fichier DAG : `dags/openfood_pipeline_dag.py`

## 5. Base PostgreSQL

La base métier est définie par `POSTGRES_DB=openfood_db` dans l'environnement par défaut.

Tables principales :

- `produit` : fiche produit, code OpenFoodFacts, nom, quantité, NutriScore, NOVA, image, URL
- `valeurs_nutritionnelles` : sucre, sel, graisses saturées, fibres, protéines, énergie
- `marque` : marques produits
- `categorie` : catégories et groupes nutritionnels
- `ingredient` : ingrédients bruts
- `ingredient_standardise` : forme canonique d'un ingrédient
- `synonyme_ingredient` : synonymes issus du clustering, du LLM ou d'une saisie manuelle
- `allergene`, `label`, `pays` : tables de référence
- `product_similarity` : recommandations similaires ou plus saines
- `rejected_products_review` : produits rejetés consultables pour révision
- `etl_import_history` : historique des imports

Tables d'association :

- `produit_categorie`
- `produit_ingredient`
- `produit_allergene`
- `produit_label`
- `produit_pays`

## 6. Standardisation des ingrédients

Scripts :

- `dags/scripts/standardize_ingredients.py`
- `dags/scripts/cluster_ingredients.py`

Le clustering TF-IDF est toujours disponible :

- extraction des ingrédients uniques chargés dans PostgreSQL
- vectorisation TF-IDF par n-grammes de caractères 2-4
- regroupement avec DBSCAN sur distance cosinus
- seuil de similarité configurable avec `INGREDIENT_CLUSTER_SIMILARITY`
- choix du représentant le plus fréquent comme forme canonique
- stockage dans `ingredient_standardise` et `synonyme_ingredient`

L'enrichissement LLM est optionnel :

```env
ENABLE_LLM_INGREDIENT_SYNONYMS=true
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Pour une remise académique ou un dépôt public, aucune clé API réelle ne doit être incluse dans le projet.

## 7. Moteur de recommandation

Le moteur de recommandation est défini dans `dags/scripts/build_similarity.py`.

Il génère deux types de recommandations :

- `similaire` : produits proches selon plusieurs critères
- `plus_saine` : produits offrant une amélioration du score santé

Modes de similarité utilisés :

| Mode | Description |
|------|-------------|
| `meme_categorie` | Produits de même catégorie principale |
| `profil_nutritionnel` | Distance sur les nutriments normalisés |
| `score_nutritionnel_global` | Proximité du profil NutriScore |
| `niveau_transformation_nova` | Proximité du niveau NOVA |
| `similitude_ingredients` | Similarité textuelle des ingrédients |

Les résultats sont stockés dans `product_similarity`.

## 8. Application Streamlit

Point d'entrée : `streamlit_app/main.py`

Pages et fonctionnalités :

- accueil : recherche, filtres, tri multicritère et cartes produits
- détail produit : fiche complète, image, valeurs nutritionnelles et recommandations
- insights : distributions, tendances et statistiques globales
- comparateur : comparaison côte à côte de plusieurs produits
- panier/favoris : sauvegarde de produits sélectionnés
- profil santé : lecture personnalisée selon certains critères nutritionnels
- admin : révision des produits rejetés, CRUD et suggestions de catégories

## 9. Prérequis

- Docker
- Docker Compose
- Git

## 10. Démarrage Rapide

Depuis la racine du projet :

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Une fois la stack démarrée :

1. Ouvrir Airflow sur http://localhost:8080
2. Vérifier que le DAG `openfood_pipeline_united_states` est visible
3. Configurer si nécessaire le mode de source dans `.env`
4. Lancer un run manuel du DAG si la base doit être alimentée
5. Ouvrir Streamlit sur http://localhost:8501

Exemple avec une source locale :

```env
OPENFOOD_SOURCE_MODE=local
OPENFOOD_LOCAL_FILE=data/bronze/openfood/local/openfoodfacts-products.jsonl.gz
OPENFOOD_MAX_ROWS=500
```

Exemple avec les exports officiels :

```env
OPENFOOD_SOURCE_MODE=official
OPENFOOD_IMPORT_MODE=auto
OPENFOOD_MAX_ROWS=500
```

## 11. Accès aux Services

| Service | URL | Identifiants |
|---------|-----|--------------|
| Streamlit | http://localhost:8501 | - |
| Airflow | http://localhost:8080 | `admin` / `admin123` |
| Adminer | http://localhost:8081 | serveur `postgres`, user `postgres`, password `postgres123` |
| MinIO API | http://localhost:9000 | - |
| MinIO Console | http://localhost:9001 | `minioadmin` / `minioadmin123` |
| JupyterLab | http://localhost:8888 | token `openfood2024` |

## 12. État Attendu du Projet

- Airflow démarre et expose le DAG `openfood_pipeline_united_states`
- MinIO contient les buckets `bronze`, `silver` et `gold`
- la couche Silver contient les sorties intermédiaires de nettoyage et le fichier final Parquet
- PostgreSQL contient les tables normalisées, les index et l'historique `etl_import_history`
- les ingrédients standardisés sont disponibles dans `ingredient_standardise` et `synonyme_ingredient`
- les recommandations sont disponibles dans `product_similarity`
- Streamlit permet la navigation entre recherche, détails, insights, comparaison, favoris, profil santé et administration
