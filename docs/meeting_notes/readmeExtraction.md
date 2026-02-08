# Étape 1 – Extraction des données OpenFoodFacts

## Contexte
Ce projet s’inscrit dans le cadre du cours **MIG8110** et a pour objectif l’extraction, la préparation et l’analyse des données issues de la base **OpenFoodFacts**.

Cette étape correspond à la **phase d’extraction des données**, qui constitue la première brique du pipeline de traitement (Extraction → Transformation → Analyse).

---

## Données sources

Les données utilisées proviennent du site officiel **OpenFoodFacts**.

Fichier source principal :

Ce fichier contient l’ensemble des produits alimentaires référencés par OpenFoodFacts, avec leurs informations nutritionnelles, catégories, marques et pays.

Source officielle :
https://world.openfoodfacts.org/data/

---

## Gestion du fichier de données brutes

Le fichier de données brutes est :
- compressé au format **CSV.gz**
- volumineux (plusieurs centaines de Mo)

Dans ce projet, **le fichier de données brutes compressé a été poussé dans le dépôt**, afin de permettre une reproduction directe des traitements réalisés lors de l’étape d’extraction.

---

## Extraction et préparation des données

L’extraction et le premier filtrage des données sont réalisés à l’aide d’un **script Python**, qui remplace le notebook initial afin de faciliter l’automatisation et la reproductibilité.

Script d’extraction :

Ce script permet notamment :
- de charger le fichier CSV compressé,
- de filtrer les produits (ex. produits du Canada),
- de sélectionner les attributs pertinents,
- de produire un jeu de données intermédiaire utilisable pour les étapes suivantes du projet.

---

## Résultat de l’étape d’extraction

À l’issue de cette étape :
- les données brutes OpenFoodFacts sont disponibles localement,
- un sous-ensemble de données filtrées est généré,
- les données sont prêtes pour l’étape suivante de **transformation et nettoyage**.

---

## Remarque méthodologique

La séparation entre :
- les **données brutes**,
- et les **scripts d’extraction et de traitement**

permet de respecter les bonnes pratiques en science des données et en ingénierie logicielle, tout en assurant la traçabilité et la reproductibilité des résultats.
