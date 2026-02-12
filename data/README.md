README — Dossier `data`
========================

Objectif
--------
Ce document explique l'organisation, les conventions et les procédures d'ingestion/validation des jeux de données du projet. Il sert de référence pour les coéquipiers et l'enseignant.

Arborescence attendue
---------------------
- `raw/`   : données importées brutes (format original). Ne pas modifier les fichiers ici après ingestion.
- `bronze/`: copies issues de l'ingestion, nettoyages minimes (suppression des fichiers corrompus, normalisation d'encodage). Données toujours proche du RAW.
- `silver/`: données transformées, normalisées et jointes. Structure prête pour usages analytiques intermédiaires.
- `gold/`  : datasets finaux, tables analytiques ou exports destinés au rapport/BI.

Formats et conventions
----------------------
- Formats acceptés : CSV (UTF-8, séparateur `,` ou `;`), JSON (newline-delimited recommandé), Parquet.
- Nom des fichiers : `source_datasetname_YYYYMMDD[_vN].ext` (ex : `openfoodfacts_products_20240210_v1.csv`).
- Pour les CSV : inclure un fichier `schema_<dataset>.yaml` décrivant les colonnes et types si disponibles.
- Les fichiers doivent être horodatés et versionnés quand une nouvelle extraction est ajoutée.

Schémas et métadonnées
----------------------
- Pour chaque dataset majeur, créer un fichier de métadonnées `_<dataset>_METADATA.yaml` ou `_<dataset>_README.md` (emplacement : même dossier que les fichiers de données). Ce fichier doit contenir :
  - origine / URL d'obtention
  - date d'extraction
  - descriptif des colonnes (nom, type, description, valeurs manquantes attendues)
  - volume approximatif (taille, nombre de lignes)
  - responsable / contact

Procédure d'ingestion (checklist)
--------------------------------
1. Placer le fichier original dans `data/raw/` avec le nom conforme.
2. Ajouter le fichier de métadonnées minimal (`_METADATA.yaml`) décrivant la source et la date.
3. Lancer le script d'ingestion (ex : `scripts/ingest.py` ou commande fournie). Exemple :

```bash
python scripts/ingest.py --source data/raw/openfoodfacts_products_20240210_v1.csv --target data/bronze/
```

4. Vérifier le journal d'ingestion et le fichier de log (`logs/ingest_*.log`).
5. Exécuter les validations de schéma et qualité (ex : tests unitaires ou utilitaire `scripts/validate_data.py`).
6. Si succès, déplacer/archiver la version ingérée dans `data/bronze/` et mettre à jour le fichier METADATA.

Validations recommandées
------------------------
- Encodage UTF-8 correct.
- Présence des colonnes obligatoires.
- Pas de lignes dupliquées (ou documenter la duplication attendue).
- Valeurs aberrantes hors plages attendues (ex : nutriments négatifs).
- Comptage ligne avant/après ingestion pour détecter pertes.

Bonnes pratiques de stockage
---------------------------
- Ne PAS stocker d'informations personnelles identifiables (PII) non pseudonymisées. Si nécessaire, pseudonymiser avant stockage dans `silver/` ou `gold/`.
- Conserver les fichiers `raw` intacts pour audit.
- Garder un historique des versions (ne pas écraser une extraction existante sans archivage).
- Si le dataset est volumineux (>100MB), préférer Parquet pour stockage et traitement.

Exemples de schéma (extrait)
----------------------------
- `products.csv` :
  - `code` (string) : code-barres unique
  - `product_name` (string)
  - `brands` (string)
  - `nutrition_grade` (string)
  - `nutriments_energy_kcal` (float)

Commandes utiles
----------------
Installer dépendances du projet :

```bash
pip install -r requirement.txt
```

Exécuter ingestion (exemple) :

```bash
python scripts/ingest.py --source data/raw/<file> --target data/bronze/
```

Valider dataset :

```bash
python scripts/validate_data.py --file data/bronze/<file>
```

Archivage et nettoyage
----------------------
- Archiver les anciennes versions dans `data/archive/YYYYMMDD/`.
- Nettoyer les fichiers temporaires dans `data/tmp/` après exécution des pipelines.

Rôles et contacts
------------------
- Responsable données : à définir (mettre le nom et mail du membre responsable ici).
- Pour questions techniques : créer une issue sur le repo ou contacter le responsable.

À faire / améliorations futures
-------------------------------
- Ajouter scripts d'ingestion/validation automatisés (`scripts/ingest.py`, `scripts/validate_data.py`) si absents.
- Générer automatiquement les METADATA à partir d'un ETL initial.
- Mettre en place des tests d'intégration pour vérifier les étapes bronze→silver→gold.

Fin du document
