# Schéma de la base de données et dictionnaire de données

Ce document décrit le schéma relationnel utilisé par le projet OpenFoodFacts (local), le dictionnaire des tables/colonnes, les relations, index et commandes utiles pour l'administration.

Emplacement des scripts SQL
- `database/schema/create_tables.sql` : création des tables, contraintes et index.
- `database/migrations/` :  migrations versionnées à utiliser en production.

Connexion (exemple)
- Driver : PostgreSQL
- Host : `localhost`
- Port : `5432`
- Database : `openfoodfacts_canada`
- Username : `postgres`
- Password : `admin`

Résumé du modèle
- Entité principale : `produit` (chaque produit identifié par `code_produit`).
- Table 1-1 : `valeurs_nutritionnelles` (détails nutritionnels, FK vers `produit`).
- Entités de référentiel (dimensions) : `marque`, `categorie`, `pays`, `ingredient`, `allergene`, `label`.
- Tables d'association N-N : `produit_categorie`, `produit_ingredient`, `produit_pays`, `produit_allergene`, `produit_label`.

Tables et dictionnaire

1) `marque`
- `id_marque` SERIAL PRIMARY KEY
- `brands` TEXT UNIQUE NOT NULL — nom de la marque. Index : `idx_marque_nom`.
Description : référence des marques; FK utilisé dans `produit.id_marque`.

2) `categorie`
- `id_categorie` SERIAL PRIMARY KEY
- `categorie` TEXT NOT NULL — nom de la catégorie
- `pnns_groups_1` TEXT — regroupement PNNS
- `parent_id` INTEGER NULL — FK auto-référentielle vers `categorie(id_categorie)` (hiérarchie)
Index : `idx_categorie_nom`.

3) `pays`
- `id_pays` SERIAL PRIMARY KEY
- `countries_en` TEXT UNIQUE NOT NULL — nom du pays en anglais
Index : `idx_pays_nom`.

4) `ingredient`
- `id_ingredient` SERIAL PRIMARY KEY
- `ingredients_nom` TEXT UNIQUE NOT NULL — nom de l'ingrédient
Index : `idx_ingredient_nom`.

5) `allergene`
- `allergen_id` SERIAL PRIMARY KEY
- `allergens` TEXT UNIQUE NOT NULL — nom de l'allergène
Index : `idx_allergene_nom`.

6) `label`
- `label_id` SERIAL PRIMARY KEY
- `labels` TEXT UNIQUE NOT NULL — nom du label
Index : `idx_label_nom`.

7) `produit` (table principale)
- `code_produit` BIGINT PRIMARY KEY — identifiant (code-barres) du produit.
- `nom_produit` TEXT NOT NULL — libellé du produit. Index : `idx_produit_nom`.
- `quantite` TEXT — étiquette quantité (ex : "500 g").
- `nutrition_grade` CHAR(1) — lettre du grade nutritionnel (A..E).
- `nutriscore_score` INTEGER — score Nutri-Score.
- `nova_group` INTEGER — classification NOVA.
- `url` TEXT — lien vers la fiche produit OpenFoodFacts.
- `image_url`, `image_small_url`, `image_ingredients_url`, `image_ingredients_small_url`, `image_nutrition_url` — URL des images.
- `id_marque` INTEGER NULL — FK vers `marque(id_marque)` (ON DELETE SET NULL).

Remarque : `code_produit` est défini BIGINT — certains exports peuvent contenir des codes non numériques ; le loader du projet convertit en string si nécessaire. Vérifier la consistance des types lors des imports.

8) `valeurs_nutritionnelles` (1-1 avec `produit`)
- `code_produit` BIGINT PRIMARY KEY REFERENCES `produit(code_produit)` ON DELETE CASCADE
- `saturated_fat_100g`, `sugars_100g`, `fiber_100g`, `proteins_100g`, `salt_100g`, `carbohydrates_100g`, `fat_100g` — NUMERIC (valeurs par 100g)

Tables d'association N-N
- `produit_categorie` (code_produit, id_categorie) PK composite — cascade on delete
- `produit_ingredient` (code_produit, id_ingredient)
- `produit_pays` (code_produit, id_pays)
- `produit_allergene` (code_produit, allergen_id)
- `produit_label` (code_produit, label_id)

Contraintes et comportements importants
- Clefs primaires et clés étrangères appliquées avec `ON DELETE CASCADE` pour les liens produit↔dimension (permet d'effacer proprement un produit).
- `marque.id_marque` est `ON DELETE SET NULL` pour conserver le produit si la marque est supprimée.
- Unicité : plusieurs champs référentiels (`brands`, `ingredients_nom`, `allergens`, `labels`, `countries_en`) sont `UNIQUE` pour éviter doublons.

Indexation
- Indexs créés pour accélérer les recherches par nom : `idx_produit_nom`, `idx_categorie_nom`, `idx_ingredient_nom`, `idx_allergene_nom`, `idx_label_nom`, `idx_marque_nom`, `idx_pays_nom`.

Exemples de requêtes utiles
- Compter les produits :
  ```sql
  SELECT COUNT(*) FROM produit;
  ```
- Produits d'une marque :
  ```sql
  SELECT p.* FROM produit p JOIN marque m ON p.id_marque = m.id_marque WHERE m.brands = 'Danone';
  ```
- Valeurs nutritionnelles pour un produit :
  ```sql
  SELECT v.* FROM valeurs_nutritionnelles v WHERE v.code_produit = 1234567890123;
  ```
- Produits par pays (exemple) :
  ```sql
  SELECT p.* FROM produit p JOIN produit_pays pp ON p.code_produit = pp.code_produit JOIN pays pa ON pp.id_pays = pa.id_pays WHERE pa.countries_en = 'Canada';
  ```

Bonnes pratiques d'ingestion
- Pré-valider les fichiers CSV / Parquet (encodage UTF-8, colonnes attendues) — voir `data/README.md`.
- Utiliser un `dry-run` (le loader du projet supporte `--dry-run`) pour vérifier le format sans écrire en base.
- Convertir ou normaliser les identifiants (`code_produit`) pour éviter erreurs de type : conserver des chaînes si nécessaire.
- Utiliser des transactions groupées et journaux (logs) pour pouvoir rejouer/rollback en cas d'échec.

Sauvegarde et restauration
- Sauvegarder la base (dump) :
  ```bash
  pg_dump -U postgres -h localhost -Fc openfoodfacts_canada > openfoodfacts_canada.dump
  ```
- Restaurer :
  ```bash
  pg_restore -U postgres -h localhost -d openfoodfacts_canada --clean openfoodfacts_canada.dump
  ```

Migrations
- Préférer un gestionnaire de migrations (ex : Alembic) pour les évolutions de schéma plutôt que des scripts `CREATE TABLE` manuels.

Vérifications et qualité
- Mettre en place des tests d'intégration qui :
  - créent une base de test
  - appliquent `create_tables.sql`
  - exécutent les loaders sur un petit échantillon
  - comparent le nombre d'enregistrements et quelques valeurs clés

Fichier source
- Voir [database/schema/create_tables.sql](database/schema/create_tables.sql) pour la définition canonique.

Responsables
- Indiquer dans `docs/MAINTAINERS.md` la personne en charge du schéma et des migrations.

Fin du document
