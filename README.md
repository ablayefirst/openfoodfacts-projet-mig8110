# OpenFoodFacts Data Platform (MIG8110)

## Plateforme data OpenFoodFacts avec pipeline ETL, entreposage objet, IA et exploration Streamlit

Ce projet met en place une chaîne complète de traitement de données autour des exports OpenFoodFacts :

- extraction des exports officiels OpenFoodFacts (full dump, deltas ou fichier local)
- dépôt des données brutes dans MinIO (zone Bronze)
- nettoyage en deux passes et normalisation en zone Silver (Parquet)
- chargement dans PostgreSQL selon un schéma relationnel normalisé
- standardisation des ingrédients par clustering TF-IDF avec enrichissement LLM optionnel
- construction des recommandations produit via un moteur de similarité multi-modal
- exploration et administration via une application Streamlit multi-pages

L'architecture est orchestrée avec Docker Compose et Airflow.

## 1. Objectifs

- Extraire les produits OpenFoodFacts depuis les exports officiels ou une source locale
- Contrôler la qualité minimale des données avant ingestion (contrats qualité en deux passes)
- Normaliser les champs métier : catégories, NutriScore, quantités, ingrédients
- Charger un schéma PostgreSQL normalisé avec index optimisés
- Standardiser les ingrédients par regroupement sémantique (TF-IDF + LLM optionnel)
- Générer des recommandations produit (similaires et plus sains) via 5 modes de similarité
- Offrir une interface Streamlit pour la recherche, l'analyse, la comparaison et l'administration

## 2. Architecture Technique

Tous les composants sont définis dans `docker-compose.yml`.

Services principaux :

- `postgres` : base métier PostgreSQL
- `airflow-postgres` : base de métadonnées Airflow
- `minio` et `minio-init` : stockage objet S3-compatible et initialisation des buckets
- `airflow-webserver`, `airflow-scheduler`, `airflow-init` : orchestration ETL
- `streamlit-app` : interface utilisateur principale
- `adminer` : exploration de la base
- `jupyter` : exploration et prototypage
- `build-similarity` : service éphémère pour le calcul de similarité

Vue simplifiée :

```text
Source de données
      |
      +--> Exports officiels OpenFoodFacts
      |     +--> Full dump (full)
      |     +--> Delta exports (delta)
      |
      +--> Fichier local JSONL (mode local)
      |
      v
Airflow DAG
extract -> upload -> first_clean -> second_clean -> merge -> load
        -> standardize_ingredients -> build_similarity
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
      +--> ingredient_standardise + synonyme_ingredient (clustering TF-IDF / LLM)
      +--> product_similarity (recommandations)
      |
      v
Streamlit (dashboard, insights, comparateur, admin)
```

## 3. Architecture Data

### Bronze

- Données brutes issues d'un full, d'un delta ou d'un fichier local
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
- `file2_bad.jsonl` : lignes échouant au premier contrat mais encore récupérables
- `recovered.parquet` : lignes sauvées au second nettoyage
- `reject.jsonl` : lignes définitivement invalides après la seconde tentative

Le fichier Silver final chargé dans PostgreSQL est la fusion dédupliquée de `file1_good` et `recovered`.

### Chargement PostgreSQL

- La sortie Silver est chargée dans PostgreSQL via SQLAlchemy ORM (inserts idempotents)
- Le schéma relationnel est créé automatiquement avant chargement
- L'historique des imports est tracé dans `etl_import_history`
- Des index sont créés pour accélérer les recherches
- Fichiers principaux :
  - `dags/scripts/load_to_postgres.py`
  - `dags/sql/create_tables.sql`
  - `dags/sql/explain_indexes.sql`

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
8. `build_similarity`

Planification :

- `timedelta(days=14)`
- `catchup=False`

Stratégie d'ingestion :

- premier chargement : dump complet OpenFoodFacts ou fichier local JSONL
- chargements incrémentaux : delta exports non encore importés
- rafraîchissement complet périodique toutes les 56 jours (mode `auto`)

Modes de source pris en charge :

- `OPENFOOD_SOURCE_MODE=official` : exports OpenFoodFacts (`full`, `delta` ou `auto`)
- `OPENFOOD_SOURCE_MODE=local` : fichier JSONL local défini par `OPENFOOD_LOCAL_FILE`

Options utiles d'extraction :

- `OPENFOOD_FULL_MODE=direct|sample`
- `OPENFOOD_FULL_SAMPLE_SIZE`
- `OPENFOOD_FULL_SAMPLE_STRATEGY=first|random`
- `OPENFOOD_DELTA_MAX_FILES`
- `OPENFOOD_MAX_ROWS` : limite le nombre de lignes (utile en développement)

### Rôle détaillé des deux nettoyages

#### Premier nettoyage : `first_clean_from_bronze`

Lit le JSONL Bronze depuis MinIO et applique `build_row(..., recovery_mode=False)` suivi d'`evaluate_final_contract(...)`.

Contrôles appliqués :

- qualité du nom produit
- présence et normalisation des catégories
- cohérence du NutriScore
- format de quantité
- cohérence énergétique ou sel/sodium

Résultats :

- `file1_good.parquet` : lignes qui passent directement le contrat qualité final
- `file2_bad.jsonl` : lignes à tenter de récupérer

#### Second nettoyage : `second_clean_from_bad`

Relit uniquement `file2_bad.jsonl` avec `build_row(..., recovery_mode=True)` : mode plus tolérant permettant la récupération de cas limites (noms alternatifs, catégories élargies, NutriScore réconcilié de façon souple, quantités atypiques).

Résultats :

- `recovered.parquet` : lignes sauvées
- `reject.jsonl` : lignes définitivement non exploitables

Fichier DAG : `dags/openfood_pipeline_dag.py`

## 5. Standardisation des ingrédients

Script : `dags/scripts/standardize_ingredients.py` + `dags/scripts/cluster_ingredients.py`

### Étape 1 : Clustering TF-IDF (toujours actif)

- Extrait les ingrédients uniques de tous les produits chargés
- Applique une vectorisation TF-IDF (n-grammes de caractères 2–4) + similarité cosinus
- Regroupe les ingrédients similaires par clustering hiérarchique (seuil : 0.80)
- Élit le représentant le plus fréquent par cluster → stocké dans `ingredient_standardise`
- Enregistre les membres du cluster comme synonymes (`source='cluster'`) dans `synonyme_ingredient`

### Étape 2 : Enrichissement LLM (optionnel)

Activé via `ENABLE_LLM_INGREDIENT_SYNONYMS=true` + `OPENAI_API_KEY`.

- Envoie les noms canoniques à GPT-4o-mini (20 ingrédients par appel)
- Génère des noms anglais standardisés et des synonymes supplémentaires
- Cache les résultats localement (JSON) pour éviter les appels redondants
- Stocké dans `synonyme_ingredient` avec `source='llm'` et un score de confiance

Paramètres de configuration :

- `INGREDIENT_CLUSTER_SIMILARITY=0.80`
- `INGREDIENT_CLUSTER_MIN_SAMPLES=2`
- `INGREDIENT_CLUSTER_MIN_FREQ=2`
- `INGREDIENT_CLUSTER_DRY_RUN=false`
- `ENABLE_LLM_INGREDIENT_SYNONYMS=false`
- `OPENAI_MODEL=gpt-4o-mini`

## 6. Moteur de recommandation

Script : `dags/scripts/build_similarity.py`

Génère deux types de recommandations pour chaque produit :

- `similaire` : produits proches selon ≥ 2 des 5 modes ci-dessous
- `plus_saine` : produits offrant ≥ 2 améliorations de score santé (delta minimum : 3.0 pts)

### 5 modes de similarité

| Mode | Description | Seuil |
|------|-------------|-------|
| `meme_categorie` | Même catégorie principale | — |
| `profil_nutritionnel` | Distance euclidienne sur nutriments normalisés | ≥ 0.35 |
| `score_nutritionnel_global` | Proximité NutriScore | ≥ 0.50 |
| `niveau_transformation_nova` | Proximité niveau NOVA | ≥ 0.50 |
| `similitude_ingredients` | Similarité textuelle des ingrédients (TF-IDF) | ≥ 0.15 |

### Score de santé (algorithme inspiré OMS)

```
Base : 100 pts
Pénalités → Sucre > 25g : -2/g · Sel > 6g : -3/g · Graisses sat. > 20g : -2/g · NOVA 4 : -3
Bonus     → Fibres > 3g : +2/g · Protéines > 3g : +1/g
Résultat  → normalisé entre 0 et 100
```

Résultats stockés dans la table `product_similarity` (code_1, code_2, similarity_score, recommendation_type).

## 7. Base PostgreSQL

### Tables principales

- `produit` : fiche produit (code, nom, marque, catégorie principale, NutriScore, NOVA, URLs)
- `valeurs_nutritionnelles` : données nutritionnelles (1:1 avec `produit`)
- `marque` : marques (M:1)
- `categorie` : catégories avec groupes PNNS
- `ingredient` : ingrédients bruts
- `ingredient_standardise` : formes canoniques (fréquence, cluster_id)
- `synonyme_ingredient` : variantes d'ingrédients (source : `cluster` / `llm` / `manual`)
- `allergene`, `label`, `pays` : tables de référence

### Tables d'association (N:N)

- `produit_categorie`, `produit_ingredient`, `produit_allergene`, `produit_label`, `produit_pays`

### Tables admin et suivi

- `rejected_products_review` : produits rejetés stockés en JSONB pour révision manuelle
- `product_category_suggestions` : suggestions automatiques de catégorie
- `product_similarity` : recommandations générées par le moteur de similarité
- `etl_import_history` : traçabilité complète de chaque import (type, timestamps, comptages)

### Index créés automatiquement

- `idx_produit_nom`, `idx_categorie_nom`, `idx_ingredient_nom`, `idx_allergene_nom`
- `idx_label_nom`, `idx_marque_nom`, `idx_pays_nom`
- `idx_etl_import_history_imported_at`, `idx_etl_import_history_type_end_ts`

## 8. Application Streamlit

Point d'entrée : `streamlit_app/main.py`

Pages disponibles :

| Page | Fonctionnalité |
|------|---------------|
| Accueil | Recherche par nom, filtre catégorie, NutriScore, sucre, sel — tri multicritère |
| Détail produit | Fiche complète + valeurs nutritionnelles + image + produits similaires |
| Insights | Distributions, tendances, statistiques globales |
| Comparateur | Comparaison côte-à-côte de plusieurs produits |
| Panier / Favoris | Sauvegarde et gestion de produits favoris |
| Admin | Révision des produits rejetés, CRUD, suggestions de catégories |

Caractéristiques techniques :

- Connexion PostgreSQL avec pooling (SQLAlchemy)
- Cache d'images produits (téléchargées et stockées localement)
- Navigation multi-pages avec menu latéral (`streamlit_app/top_menu.py`)

## 9. Prérequis

- Docker et Docker Compose
- Git

## 10. Démarrage Rapide

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Une fois la stack démarrée :

1. Ouvrir Airflow sur http://localhost:8080
2. Vérifier que le DAG `openfood_pipeline_united_states` est visible
3. Configurer si nécessaire le mode de source dans `.env`
4. Lancer un run manuel si nécessaire
5. Ouvrir Streamlit sur http://localhost:8501

Exemple avec fichier local :

```env
OPENFOOD_SOURCE_MODE=local
OPENFOOD_LOCAL_FILE=data/bronze/openfood/local/openfood_local.jsonl
```

Exemple avec source officielle :

```env
OPENFOOD_SOURCE_MODE=official
OPENFOOD_IMPORT_MODE=auto
```

## 11. Accès aux Services

| Service | URL | Identifiants |
|---------|-----|-------------|
| Streamlit (dashboard) | http://localhost:8501 | — |
| Airflow | http://localhost:8080 | admin / admin123 |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin123 |
| Adminer | http://localhost:8081 | postgres / postgres123 |
| JupyterLab | http://localhost:8888 | token : openfood2024 |
| MinIO API | http://localhost:9000 | — |

## 12. État Attendu du Projet

- Airflow démarre et expose le DAG `openfood_pipeline_united_states`
- MinIO contient les buckets `bronze`, `silver` et `gold` initialisés
- La couche Silver contient les sorties intermédiaires de nettoyage et le fichier final Parquet
- PostgreSQL contient les tables normalisées, les ingrédients standardisés et `etl_import_history`
- Les index SQL sont créés
- La table `product_similarity` est alimentée par le moteur de recommandation
- Streamlit permet la navigation entre dashboard, tendances, comparaison, profil santé et administration
