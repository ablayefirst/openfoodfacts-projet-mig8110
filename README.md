# OpenFood Web (FastAPI + PostgreSQL)

## Objectif

Application web permettant la recherche et la consultation de produits OpenFoodFacts.

Fonctionnalités principales :
- Recherche par nom, marque, catégorie
- Filtrage par allergènes
- Tri par nom, NutriScore ou score nutritionnel
- Page détail produit
- Génération de code-barres
- Affichage des images via l’API officielle OpenFoodFacts

---

## Technologies utilisées

Backend :
- FastAPI (framework API Python)
- Uvicorn (serveur ASGI)
- SQLAlchemy (ORM et requêtes SQL)
- psycopg2-binary (driver PostgreSQL)

Frontend :
- Jinja2 (templates HTML)
- StaticFiles (CSS, images, barcodes)

Base de données :
- PostgreSQL

Autres :
- requests (API OpenFoodFacts)
- python-barcode + pillow (génération code-barres)
- pandas (utilisé uniquement pour scripts de chargement CSV si nécessaire)

---

## Structure du dossier app/
app/
│
├── main.py # Application FastAPI (routes + logique)
├── db.py # Connexion SQLAlchemy (engine + SessionLocal)
├── models.py # Modèles SQLAlchemy (Product, etc.)
│
├── templates/
│ ├── index.html # Page liste / recherche
│ └── product.html # Page détail produit
│
└── static/
├── style.css
└── barcodes/ # Images générées dynamiquement

---

## Configuration de la base de données

L’application utilise une variable d’environnement :

DATABASE_URL

Exemple pour PostgreSQL local :

postgresql+psycopg2://postgres:admin@127.0.0.1:5432/openfoodfacts_canada

Important :
- Utiliser 127.0.0.1 au lieu de localhost (évite les problèmes IPv6)
- Vérifier que PostgreSQL est démarré
- Vérifier que le mot de passe est correct

---

## Connexion SQLAlchemy attendue (db.py)

Le fichier db.py doit contenir :

- create_engine(DATABASE_URL, pool_pre_ping=True)
- SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

---

## Conformité modèle application ↔ base de données

La base de données est normalisée (tables produit + tables N-N).

L’application web attend un modèle “plat” de type :

- code
- product_name
- brands
- categories
- ingredients_text
- allergens_tags
- nutriscore_grade
- nutriscore_score
- nova_group

Pour éviter des JOIN complexes côté FastAPI, il est recommandé de créer une VIEW PostgreSQL.

---

## VIEW recommandée côté PostgreSQL

Créer une vue produit_view :

```sql
CREATE OR REPLACE VIEW produit_view AS
SELECT
  p.code_produit::text AS code,
  p.nom_produit        AS product_name,
  m.brands             AS brands,
  p.nutrition_grade    AS nutriscore_grade,
  p.nutriscore_score   AS nutriscore_score,
  p.nova_group         AS nova_group,
  p.url                AS product_url,

  COALESCE(string_agg(DISTINCT c.categorie, ', '), '') AS categories,
  COALESCE(string_agg(DISTINCT i.ingredients_nom, ', '), '') AS ingredients_text,
  COALESCE(string_agg(DISTINCT a.allergens, ', '), '') AS allergens_tags

FROM produit p
LEFT JOIN marque m ON p.id_marque = m.id_marque
LEFT JOIN produit_categorie pc ON pc.code_produit = p.code_produit
LEFT JOIN categorie c ON c.id_categorie = pc.id_categorie
LEFT JOIN produit_ingredient pi ON pi.code_produit = p.code_produit
LEFT JOIN ingredient i ON i.id_ingredient = pi.id_ingredient
LEFT JOIN produit_allergene pa ON pa.code_produit = p.code_produit
LEFT JOIN allergene a ON a.allergen_id = pa.allergen_id
GROUP BY
  p.code_produit,
  p.nom_produit,
  m.brands,
  p.nutrition_grade,
  p.nutriscore_score,
  p.nova_group,
  p.url;
 
 Ensuite, mapper le modèle SQLAlchemy sur cette VIEW.

Lancer l’application en local
1. Installer les dépendances

À la racine du projet :

pip install -r requirements.txt

2. Définir la variable d’environnement (PowerShell)

$env:DATABASE_URL="postgresql+psycopg2://postgres:admin@127.0.0.1:5432/openfoodfacts_canada"

3. Lancer le serveur

uvicorn app.main:app --reload

4. Accéder à l’application

http://127.0.0.1:8000

Débogage

Si erreur SQLAlchemy :

Vérifier le mot de passe PostgreSQL

Vérifier que la base existe

Vérifier que le port est correct

Si import sqlalchemy non résolu :

Vérifier que VS Code utilise le bon environnement Python (.venv)

Si erreur de connexion :

Tester la connexion avec psql

Vérifier netstat -aon | findstr 5432

Notes importantes

Le mot de passe ne s’affiche pas dans psql (normal).

Si les tables sont vides, il faut charger les données via le script load_data.py.

L’application peut fonctionner uniquement en mode DB (pas besoin de CSV si base remplie).
