# Projet Open Food Facts – Canada  
**MIG8110 – Devoir 3 | Phase de démarrage (End-to-End)**

##  Objectif du projet
Développer une application web permettant d’explorer et de comparer la qualité nutritionnelle des produits alimentaires vendus au Canada à partir des données Open Food Facts.

L’application permet notamment de :
- comparer les profils nutritionnels par catégorie de produits
- analyser la distribution des sucres, des matières grasses et du sel
- identifier les catégories les plus énergétiques
- étudier la relation entre Nutri-Score et valeurs nutritionnelles

##  Jeu de données
Source : https://world.openfoodfacts.org  

Périmètre :
- Produits **vendus au Canada**
- Échantillon représentatif extrait à partir du dump officiel Open Food Facts (`.csv.gz`)
- Environ 20–100k produits selon les critères de filtrage

---

##  Architecture du projet (pipeline)
Le projet suit une approche **ETL simplifiée**, avec plusieurs zones de staging :

Raw (dump OFF .csv.gz)
↓
Bronze (échantillon Canada filtré)
↓
Silver (données nettoyées et structurées)
↓
Base de données
↓
Application Web (visualisation)


## Démarrage docker

### Prérequis
- Docker Desktop installé et lancé
- Git

### Pour les membres de l'équipe (déjà sur le projet)

```bash
# 1. Aller sur la branche develop (contient tout)
git checkout develop
git pull origin develop

# 2. Configurer l'environnement (une seule fois)
cp .env.example .env

# 3. Lancer l'application
docker compose up -d
docker compose ps
   ```
# Vérifier que tout tourne
docker compose ps
   ```

**C'est tout !** L'application est accessible sur :
- Airflow : http://localhost:8080 (admin/admin123)
- MinIO : http://localhost:9001 (minioadmin/minioadmin123)
- Jupyter : http://localhost:8888 (token: openfood2024)
- Dash : http://localhost:8050

### En cas de problème
- Vérifiez que Docker Desktop est bien lancé
- Regardez les logs : `docker compose logs -f`