# Application Streamlit – Santé & Nutrition

Cette application Streamlit permet d’explorer les produits alimentaires de la base *OpenFoodFacts Canada* en mettant l’accent sur les aspects santé et nutrition :

- Recherche par nom de produit et par catégorie
- Filtre sur le NutriScore (A → E)
- Filtre sur la teneur en sucre (g/100g)
- Tri par NutriScore, sucre ou sel
- Cartes produits avec image, catégories, NutriScore et résumés nutritionnels
- Accès à une page de **détail produit** (via `pages/01_detail_produit.py`)

---

## 1. Prérequis

- **Python** 3.9+ installé
- **PostgreSQL** accessible (en local ou via Docker)
  - Base de données : `openfoodfacts_canada` (par défaut)
  - Tables et données déjà chargées (voir le dossier `database/` du projet pour le schéma et les scripts de chargement)
- (Optionnel) **Docker / docker-compose** si tu pilotes la base via les conteneurs du projet

---

## 2. Récupérer le projet

```bash
# Cloner le dépôt (adapter l’URL à ton cas)
git clone <URL_DU_REPO>
cd openfoodfacts-projet-mig8110
```

Si tu travailles déjà dans ce répertoire, tu peux passer cette étape.

---

## 3. Créer et activer un environnement virtuel

Sous **Windows (PowerShell)** :

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Sous **macOS / Linux** :

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## 4. Installer les dépendances Python

Les dépendances principales (dont Streamlit et psycopg2) sont définies dans le `requirements.txt` à la racine du projet.

Depuis la racine du projet :

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Configuration de la base PostgreSQL

L’application Streamlit se connecte à PostgreSQL via le module `db_connection.py`. Par défaut, elle utilise les variables d’environnement suivantes :

- `POSTGRES_HOST` (défaut : `localhost`)
- `POSTGRES_DB` (défaut : `openfoodfacts_canada`)
- `POSTGRES_USER` (défaut : `postgres`)
- `POSTGRES_PASSWORD` (défaut : `admin`)
- `POSTGRES_PORT` (défaut : `5432`)

Tu peux soit :

1. **Laisser les valeurs par défaut** si ta base locale correspond (même nom de base, user et mot de passe),
2. **Ou définir ces variables d’environnement** avant de lancer Streamlit.

Exemple (Windows PowerShell) :

```bash
$Env:POSTGRES_HOST = "localhost"
$Env:POSTGRES_DB = "openfoodfacts_canada"
$Env:POSTGRES_USER = "postgres"
$Env:POSTGRES_PASSWORD = "admin"
$Env:POSTGRES_PORT = "5432"
```

Assure-toi que :

- Le serveur PostgreSQL est **démarré**,
- La base `openfoodfacts_canada` existe,
- Les tables et données ont été créées/chargées (voir `database/schema/create_tables.sql` et `database/queries/load_data.py`).

---

## 6. (Optionnel) Lancer PostgreSQL via Docker Compose

Le projet fournit un fichier `docker-compose.yml` à la racine. Si ta base PostgreSQL fait partie de cet ensemble de services, tu peux démarrer l’infrastructure avec :

```bash
# Depuis la racine du projet
docker-compose up -d
```

Vérifie ensuite que le service PostgreSQL est bien accessible avec les mêmes paramètres que ceux utilisés par l’application (host, port, base, user, mot de passe).

---

## 7. Lancer l’application Streamlit en local

1. Place-toi dans le dossier de l’app Streamlit :

```bash
cd streamlit_app
```

2. Depuis cet emplacement, lance Streamlit :

```bash
streamlit run main.py
```

3. Streamlit démarre un serveur local, généralement sur :

- http://localhost:8501

Ouvre ce lien dans ton navigateur si celui-ci ne s’ouvre pas automatiquement.

---

## 8. Navigation dans l’application

- **Page principale** (`main.py`) :
  - Barre de recherche (nom de produit, catégorie)
  - Filtres sur le NutriScore et le sucre
  - Résultats affichés sous forme de cartes produits avec image, catégories, NutriScore et valeurs de sucre/sel
  - Pagination des résultats (sauf sur la vue d’accueil aléatoire)
- **Page de détail produit** (`pages/01_detail_produit.py`) :
  - Accès via le bouton « Détails » sur chaque carte ou via le menu latéral Streamlit
  - Affiche les informations détaillées d’un produit (valeurs nutritionnelles, score santé, etc. selon l’implémentation du fichier)

---

## 9. Dépannage rapide

- **Erreur de connexion à la base** :
  - Vérifier que PostgreSQL est démarré
  - Vérifier les variables d’environnement `POSTGRES_*`
  - Tester la connexion avec un client externe (psql, DBeaver, etc.)

- **Aucune donnée n’apparaît dans l’interface** :
  - Vérifier que les tables sont remplies (scripts du dossier `database/`)
  - Vérifier que la base utilisée (`POSTGRES_DB`) est bien celle qui contient les données OpenFoodFacts

Tu peux adapter ce README si la configuration de ton environnement ou de ta base de données diffère légèrement (autres noms de base, autres utilisateurs, etc.).


## 🔐 Module Administration (Streamlit)

Une interface d’administration complète a été intégrée à l’application Streamlit afin de permettre la gestion des produits directement depuis le navigateur.

### ✅ Fonctionnalités disponibles

- Authentification administrateur sécurisée
- Consultation paginée des produits
- Recherche par :
  - Code produit (exact)
  - Nom
  - Marque
  - Catégories
- Ajout d’un nouveau produit
- Modification d’un produit existant
- Suppression sécurisée d’un produit
- Gestion automatique des relations :
  - Marque
  - Catégories (table d’association `produit_categorie`)
  - Ingrédients (table d’association `produit_ingredient`)

L’administration repose entièrement sur SQLAlchemy ORM et s’intègre proprement à la base PostgreSQL via Docker.

---

### 🔑 Accès Admin

Les identifiants sont définis via variables d’environnement :


ADMIN_USER=admin
ADMIN_PASSWORD=admin123


(À modifier en production)

---

### 🛠️ Architecture technique

- **Frontend** : Streamlit
- **ORM** : SQLAlchemy 2.x
- **Base de données** : PostgreSQL 16
- **Driver** : psycopg v3
- **Déploiement** : Docker Compose

Les modèles ORM sont définis dans `models.py` et utilisent :

- `relationship`
- `column_property`
- `tables d’association`
- `select` et `string_agg` pour les champs calculés

---

### ▶️ Lancement

Après démarrage Docker :

```bash
docker compose up -d

Accéder à :

http://localhost:8501

Puis sélectionner Admin dans le menu latéral.