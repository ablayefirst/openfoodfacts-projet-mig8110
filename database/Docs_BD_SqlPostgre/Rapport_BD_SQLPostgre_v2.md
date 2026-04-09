# Rapport v2 – Base de données PostgreSQL `openfoodfacts_canada`

Ce rapport décrit la **la version actuelle du projet** :

- la base de données métier `openfoodfacts_canada` tourne **exclusivement dans Docker** (service `postgres` du `docker-compose.yml`),
- son alimentation est orchestrée **automatiquement par le DAG Airflow** `openfood_pipeline_canada`,
- les applications clientes (Streamlit, notebooks, Adminer, Airflow) consomment cette base via le réseau Docker interne.

Il ne s’agit plus d’une installation PostgreSQL locale « manuelle » connectée via SQLTools, mais d’un environnement **entièrement conteneurisé et piloté par le pipeline Airflow**.

---

## 1. Architecture actuelle autour de PostgreSQL

### 1.1. Services Docker impliqués

Le fichier [docker-compose.yml](../../docker-compose.yml) définit plusieurs services clés :

- **`postgres`** (conteneur `postgres_openfood`) :
  - héberge la base métier `openfoodfacts_canada` (tables produits, valeurs nutritionnelles, catégories, etc.) ;
  - persistance des données dans `./data/postgres` sur la machine hôte ;
  - exposé sur le port `5432` pour un accès externe si nécessaire.

- **`airflow-webserver` / `airflow-scheduler` / `airflow-postgres`** :
  - gèrent l’orchestration des tâches ETL via Airflow ;
  - stockent leurs propres métadonnées dans le service `airflow-postgres` (distinct de la base métier).

- **`minio` + `minio-init`** :
  - stockage objet pour les zones **bronze**, **silver** et **gold** ;
  - utilisés par les tâches d’extraction et de transformation.

- **`streamlit-app`** :
  - application **Streamlit – Santé & Nutrition** ;
  - se connecte à la base `openfoodfacts_canada` via les variables d’environnement `POSTGRES_*` (hôte `postgres`, port, base, user, mot de passe).

- **`adminer`** (optionnel mais très utile) :
  - interface web de gestion SQL, accessible sur `http://localhost:8081` ;
  - permet d’explorer la base `openfoodfacts_canada` directement dans le navigateur en choisissant le serveur `postgres` et la base correspondante.

L’ensemble de ces services est relié par le réseau Docker `openfood_network`.

---

## 2. Pipeline d’alimentation – DAG Airflow `openfood_pipeline_canada`

L’alimentation de la base ne se fait plus par un script unique lancé à la main, mais par un **pipeline Airflow complet** décrit dans :

- [dags/openfood_pipeline_dag.py](../../dags/openfood_pipeline_dag.py)

Ce DAG comporte 4 tâches principales :

1. **`extract_products`** (`extract_official_exports`) :
   - télécharge les exports OpenFoodFacts (full dump et/ou deltas) pour le pays configuré (`OPENFOOD_COUNTRY`, ex. *canada*) ;
   - écrit les fichiers bruts dans le répertoire de travail Airflow (souvent `/opt/airflow/data`).

2. **`upload_to_minio`** (`upload_to_minio`) :
   - envoie les fichiers bruts dans le bucket MinIO **bronze** (`MINIO_BUCKET_BRONZE`) ;
   - joue le rôle de zone de stockage durable des données sources.

3. **`transform_to_silver`** (`transform_to_silver`) :
   - lit les données brutes depuis MinIO (bronze),
   - applique les transformations et nettoyages, 
   - écrit le résultat dans le bucket **silver** (`MINIO_BUCKET_SILVER`) sous forme de fichiers déjà structurés.

4. **`load_to_postgres`** (`load_silver_to_postgres`) :
   - lit les données silver depuis MinIO,
   - applique les règles de mapping vers le schéma SQL de la base métier,
   - exécute le SQL de création/ajustement de schéma via le fichier `sql/create_tables.sql`,
   - insère ou met à jour les données dans `openfoodfacts_canada`.

L’enchaînement est le suivant :

```text
extract_products → upload_to_minio → transform_to_silver → load_to_postgres
```

Le DAG est planifié (par défaut) sur un **intervalle de 14 jours** (`schedule=timedelta(days=14)`), ce qui permet de rafraîchir régulièrement la base sans intervention manuelle.

---

## 3. Schéma de la base `openfoodfacts_canada`

Le schéma métier a pour objectif de représenter proprement les produits OpenFoodFacts et leurs attributs :

- **Table `produit`** :
  - `code_produit` (PK, code OpenFoodFacts),
  - `nom_produit`, `quantite`,
  - `nutrition_grade` (NutriScore A–E), `nutriscore_score`,
  - `nova_group`,
  - `categorie_principale`,
  - URLs (fiche OFF, images),
  - `id_marque` (FK vers `marque`).

- **Table `marque`** :
  - `id_marque` (PK),
  - `brands` (UNIQUE).

- **Table `valeurs_nutritionnelles`** :
  - `code_produit` (PK + FK),
  - `sugars_100g`, `salt_100g`,
  - `saturated_fat_100g`, `fiber_100g`, `proteins_100g`,
  - autres nutriments utiles.

- **Tables de référence** : `categorie`, `ingredient`, `pays`, `allergene`, `label` (chacune avec un champ UNIQUE sur le nom).

- **Tables d’association N‑N** : `produit_categorie`, `produit_ingredient`, `produit_pays`, `produit_allergene`, `produit_label` (clés primaires composites `code_produit` + `id_xxx`).

Toutes ces tables sont créées et maintenues à jour par les scripts SQL/ETL appelés dans la tâche `load_to_postgres`.

---

## 4. Connexion à la base dans la "réalité actuelle"

### 4.1. Depuis les services Docker

- **Airflow** se connecte à la base métier en utilisant les variables d’environnement :
  - `POSTGRES_HOST=postgres`
  - `POSTGRES_PORT`
  - `POSTGRES_DB`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`

- **Streamlit** (`streamlit-app`) utilise les mêmes variables pour construire sa chaîne de connexion.

Dans la **réalité actuelle**, ces variables sont injectées via le `docker-compose.yml` et la communication se fait **à l’intérieur du réseau Docker** (hôte `postgres`, port `5432`).

### 4.2. Depuis l’extérieur (optionnel)

Si besoin de se connecter depuis la machine hôte (par exemple avec Adminer, DBeaver ou psql) :

- hôte : `localhost`
- port : `5432`
- base : valeur de `${POSTGRES_DB}` (par défaut `openfoodf_db`)
- utilisateur : `${POSTGRES_USER}`
- mot de passe : `${POSTGRES_PASSWORD}`

La base reste donc accessible pour des analyses ponctuelles, mais **son cycle de vie et son contenu sont gérés exclusivement par le pipeline Airflow**.

---

## 5. Utilisation de la base par l’application Streamlit

L’application Streamlit consomme la base `openfoodfacts_canada` pour fournir les fonctionnalités suivantes :

- **Dashboard** :
  - recherche de produits par nom et catégorie,
  - filtres NutriScore et sucre,
  - affichage des cartes produits à partir des données de `produit` et `valeurs_nutritionnelles`.

- **Mon profil santé** :
  - calcul d’un score santé personnalisé basé sur le NutriScore, le sucre et le sel,
  - tri des produits en fonction du profil (diabète, hypertension, etc.).

- **Comparateur de produits** :
  - chargement de 2 à 3 produits par leurs `code_produit`,
  - comparaison côte à côte des valeurs nutritionnelles et des scores personnalisés.

- **Tendances** :
  - agrégations sur les NutriScore, les catégories, les niveaux de sucre par catégorie.

La cohérence et la fraîcheur des données affichées dans Streamlit dépendent donc directement de la **bonne exécution du DAG Airflow** et de la disponibilité du service `postgres` dans Docker.

---

## 6. Synthèse

En synthèse, cette v2 du rapport reflète la **réalité actuelle du projet** :

- PostgreSQL n’est plus géré "à la main" en local via des scripts ponctuels ;
- la base métier `openfoodfacts_canada` vit dans un conteneur Docker (`postgres`) et est alimentée par un **pipeline ETL Airflow** s’appuyant sur MinIO ;
- les applications (Streamlit, notebooks, Adminer, Airflow) consomment cette base au fil de l’eau, sans intervention manuelle sur les données.

Ce document complète ainsi les autres readme applicatifs (Streamlit, Airflow) en se concentrant sur le rôle central de la base PostgreSQL dans l’architecture globale.
