# Application Streamlit – Santé & Nutrition

Cette application Streamlit permet d’explorer les produits alimentaires de la base *OpenFoodFacts Canada* en mettant l’accent sur les aspects santé et nutrition.

---

## Fonctionnalités principales de l’application

### Dashboard (page principale – `main.py`)

- Recherche par **nom de produit** et **catégorie principale**.
- Filtres sur le **NutriScore (A → E)**, la **teneur en sucre (g/100g)** et une recherche libre dans les **catégories détaillées**.
- Tri des résultats par :
  - NutriScore (A → E),
  - Sucre (g/100g),
  - Sel (g/100g),
  avec choix de l’ordre croissant / décroissant.
- Affichage des résultats sous forme de **cartes produits** :
  - Image du produit (si disponible),
  - Catégorie principale et catégories détaillées,
  - NutriScore, sucre et sel,
  - Badge « Top choix » pour les meilleurs NutriScore.
- **Vue d’accueil** :
  - Affichage d’un échantillon de produits (priorité aux produits avec image),
  - Si le profil santé est activé, les 10 meilleurs produits pour l’utilisateur sont affichés en priorité.
- **Sélection pour comparateur** :
  - Case « Comparer » sur chaque carte,
  - Possibilité de sélectionner jusqu’à **3 produits** pour comparaison.

### Page « Mon profil santé » (`health_profile.py`)

- Définition d’un **profil santé personnalisé** :
  - Objectif principal : alimentation équilibrée, perte de poids, réduction du sucre, réduction du sel.
  - Contraintes : diabète (limiter le sucre), hypertension (limiter le sel).
- Le choix de l’objectif est **guidé par les contraintes** :
  - Si diabète → priorité à « réduction du sucre »,
  - Si hypertension → priorité à « réduction du sel »,
  - Les objectifs généraux (alimentation équilibrée, perte de poids) restent disponibles.
- Bouton pour **activer / désactiver** le tri personnalisé :
  - « Voir des alternatives plus saines pour moi »,
  - « Désactiver les recommandations personnalisées ».
- Le tri personnalisé influence l’ordre des produits sur le Dashboard (score santé calculé à partir du NutriScore, du sucre et du sel).

### Comparateur de produits (`pages/03_comparateur_produits.py`)

- Accessible après avoir sélectionné 2 à 3 produits sur le Dashboard.
- Affiche les produits **côte à côte** :
  - Informations générales (nom, catégories, NutriScore, NOVA),
  - Valeurs nutritionnelles principales (sucre, sel, graisses saturées, fibres, protéines).
- Si le profil santé est activé :
  - Calcul d’un **score personnalisé** pour chaque produit,
  - Mise en avant du **meilleur choix** parmi les produits comparés.

### Page de détail produit (`pages/01_detail_produit.py`)

- Accès via le bouton « Détails » sur chaque carte produit.
- Affiche :
  - Informations complètes du produit (marques, pays, labels, catégories, etc.),
  - NutriScore, NOVA et valeurs nutritionnelles détaillées,
  - Liste des ingrédients, allergènes et labels.
- Un bouton « Retour au Dashboard » permet de revenir à la page principale.

### Page « Tendances » / Insights (`pages/02_insights.py`)

- Statistiques globales sur la base de données :
  - Répartition du NutriScore,
  - Catégories les plus fréquentes,
  - Catégories les plus sucrées (avec seuil minimum de produits).
- Filtres pour restreindre les analyses (NutriScore, catégorie texte).
- Affichage sous forme de tableaux et de graphiques.

### Module d’administration (Admin)

- Interface dédiée pour la **gestion des produits** :
  - Consultation paginée,
  - Recherche multi-critères (code, nom, marque, catégories),
  - Ajout / modification / suppression de produits,
  - Gestion des relations (marques, catégories, ingrédients).
- Accès protégé par authentification (identifiants définis via variables d’environnement).

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

---

Sous **Windows (PowerShell)** :
```bash
source .venv/bin/activate
```

---

```bash
pip install --upgrade pip
```

- `POSTGRES_HOST` (défaut : `localhost`)
- `POSTGRES_PORT` (défaut : `5432`)

Tu peux soit :

$Env:POSTGRES_HOST = "localhost"


Assure-toi que :

- Le serveur PostgreSQL est **démarré**,

---

Le projet fournit un fichier `docker-compose.yml` à la racine. Si ta base PostgreSQL fait partie de cet ensemble de services, tu peux démarrer l’infrastructure avec :


Vérifie ensuite que le service PostgreSQL est bien accessible avec les mêmes paramètres que ceux utilisés par l’application (host, port, base, user, mot de passe).

## 7. Lancer l’application Streamlit en local

1. Place-toi dans le dossier de l’app Streamlit :

cd streamlit_app

3. Streamlit démarre un serveur local, généralement sur :

- http://localhost:8501

Ouvre ce lien dans ton navigateur si celui-ci ne s’ouvre pas automatiquement.

---

## 8. Navigation dans l’application

 **Page principale** (`main.py`) :
  - Barre de recherche (nom de produit, catégorie)
  - Filtres sur le NutriScore et le sucre
  - Résultats affichés sous forme de cartes produits avec image, catégories, NutriScore et valeurs de sucre/sel
  - Pagination des résultats (sauf sur la vue d’accueil aléatoire)
 **Page de détail produit** (`pages/01_detail_produit.py`) :
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


##  Module Administration (Streamlit)

Une interface d’administration complète a été intégrée à l’application Streamlit afin de permettre la gestion des produits directement depuis le navigateur.

###  Fonctionnalités disponibles

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

###  Accès Admin

Les identifiants sont définis via variables d’environnement :


ADMIN_USER=admin
ADMIN_PASSWORD=admin123


(À modifier en production)

---

###  Architecture technique

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

###  Lancement

Après démarrage Docker :

```bash
docker compose up -d
```
Accéder à :

http://localhost:8501

Puis sélectionner Admin dans le menu latéral.

---
