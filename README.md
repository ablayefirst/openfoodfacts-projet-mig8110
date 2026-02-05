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

