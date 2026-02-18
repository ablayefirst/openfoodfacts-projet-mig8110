

#  Configuration de la Connexion PostgreSQL 

établir une connexion entre Visual Studio Code et la base de données PostgreSQL à l’aide de l’extension **SQLTools**.

---

## Les Étapes

### 1️ Installer l’extension

Dans VSCode :

* Aller dans Extensions
* Rechercher : `SQLTools`
* Installer :

  * SQLTools
  * SQLTools PostgreSQL Driver

---

### 2️ Ajouter une nouvelle connexion

Dans VSCode ou dans ton votre environnement(outil) de travail:

1. Ouvrir SQLTools
2. Cliquer sur **Add New Connection**
3. Sélectionner **PostgreSQL**

---

### 3️ Paramètres de connexion

| Champ           | Valeur                   |
| --------------- | ------------------------ |
| Connection name | PostgreSQL OpenFoodFacts |
| Driver          | PostgreSQL               |
| Conection group | (vide) ou OpenFoodFacts  |
| Server          | localhost                |
| Port            | 5432                     |
| Database        | openfoodfacts_canada     |
| Username        | postgres                 |
| Password        | admin                    |

---

### 4 Tester la connexion

Cliquer sur **Test Connection**.

Si tout est correct :

✔ Connexion réussie
✔ La base apparaît dans SQLTools

---

##  Informations importantes

* PostgreSQL est installé localement.
* Le port par défaut PostgreSQL est `5432`.
* La base `openfoodfacts_canada` doit déjà être créée dans PostgreSQL:


---

##  Exécution du script SQL pour créer les tables

Une fois connecté :

1. Ouvrir le fichier `create_tables.sql`
2. Clic droit → Run Query
3. Vérifier la création des tables

---

 L’environnement de développement a été configuré sous Visual Studio Code en utilisant l’extension SQLTools afin de permettre une gestion centralisée des requêtes SQL et une connexion sécurisée à PostgreSQL.

---

## Pour charger les données dans la base 

Commande type à exécuter depuis la racine du projet :

```bash
python database/queries/load_data.py --source data/gold/dataset_nettoyer.csv --db-url "postgresql://postgres:admin@localhost:5432/openfoodfacts_canada"
```

> Optionnel : ajouter `--dry-run` pour vérifier le CSV sans rien écrire dans la base.

---

## Comment la base de données est alimentée depuis le CSV 

Le script [database/queries/load_data.py](../queries/load_data.py) sert de **pipeline d’alimentation** entre le fichier CSV nettoyé dataset_nettoyer.csv et la base PostgreSQL `openfoodfacts_canada`.

### 1. Lecture du fichier CSV

- Le chemin du fichier est passé via l’option `--source` (dans le dossier ..data/gold/ `dataset_nettoyer.csv`).
- Le script lit le fichier avec **pandas** (`pd.read_csv`).
- Si l’option `--dry-run` est utilisée, le script **n’écrit rien dans la base** : il affiche seulement le nombre de lignes/colonnes et un extrait des données pour contrôle.

### 2. Connexion à la base PostgreSQL

- L’URL de connexion est passée via `--db-url` ou utilise la valeur par défaut :
  - `postgresql://postgres:admin@localhost:5432/openfoodfacts_canada`.
- La connexion est gérée par **SQLAlchemy** (`create_engine`).
- En cas d’erreur (mauvaise URL, mauvais mot de passe, base non joignable), le script affiche un message explicite et s’arrête.

### 3. Parcours du CSV ligne par ligne

Pour chaque produit (chaque ligne du CSV), le script ouvre une **transaction** (`with engine.begin() as conn:`) et applique les étapes suivantes :

#### a) Gestion de la marque (table `marque`)

- La colonne CSV `brands` est utilisée pour retrouver ou créer la marque.
- Le script cherche `id_marque` dans la table `marque` :
  - si la marque existe déjà (`SELECT id_marque FROM marque WHERE brands = :b`),
    - il réutilise l’identifiant existant ;
  - sinon, il insère une nouvelle ligne dans `marque` et récupère l’`id_marque` généré.
- La colonne `marque.brands` est déclarée **UNIQUE** dans le schéma SQL, ce qui empêche les doublons.

#### b) Insertion du produit (table `produit`)

- Le script construit l’enregistrement à partir de plusieurs colonnes du CSV :
  - `code` → `code_produit` (clé primaire, type BIGINT)
  - `product_name` → `nom_produit`
  - `quantity` → `quantite`
  - `nutriscore_grade` → `nutrition_grade`
  - `nutriscore_score` → `nutriscore_score`
  - `nova_group` → `nova_group`
  - `url` → `url`
  - `image_url`, `image_small_url`, `image_ingredients_url`, `image_ingredients_small_url`, `image_nutrition_url` → colonnes images
  - `id_marque` récupéré à l’étape précédente.
- Le helper `format_code()` nettoie la valeur `code` (par exemple `264.0` devient "264") afin qu’elle soit compatible avec la colonne `code_produit` (BIGINT).
- Le helper `safe()` transforme les valeurs manquantes de pandas (`NaN`) en `NULL` SQL.
- L’insertion se fait avec une clause de protection :

  ```sql
  INSERT INTO produit (...)
  VALUES (...)
  ON CONFLICT DO NOTHING;
  ```

  Cela signifie que **si un produit avec le même `code_produit` existe déjà, il n’est pas réécrit ni mis à jour** : la ligne est simplement ignorée.

#### c) Insertion des valeurs nutritionnelles (table `valeurs_nutritionnelles`)

- À partir des colonnes CSV telles que `saturated_fat_100g`, `sugars_100g`, `fiber_100g`, `proteins_100g`, `salt_100g`, `carbohydrates_100g`, `fat_100g`,
  le script insère une ligne dans la table `valeurs_nutritionnelles`.
- Le lien se fait via `code_produit` (clé primaire et clé étrangère vers `produit`).
- Là aussi, la clause `ON CONFLICT DO NOTHING` est utilisée pour éviter les doublons : si des valeurs nutritionnelles existent déjà pour ce produit, elles ne sont pas modifiées.

### 4. Gestion des champs multi‑valeurs (catégories, ingrédients, labels, pays, allergènes)

Certaines colonnes CSV contiennent **plusieurs valeurs séparées par des virgules**, par exemple :

- `categories`
- `ingredients_text`
- `allergens`
- `labels`
- `countries_en`

Pour chacune de ces colonnes, le script utilise une fonction générique `insert_many_to_many(...)` qui applique toujours la même logique :

1. Vérifier que la colonne n’est pas vide (`NaN`).
2. Découper la chaîne sur `,` puis nettoyer chaque valeur (trim des espaces, suppression des vides).
3. Pour chaque valeur `v` :
   - Chercher si elle existe déjà dans la table de référence (ex. `ingredient`, `categorie`, `pays`, `allergene`, `label`) via un `SELECT`.
   - Si elle n’existe pas, l’insérer et récupérer l’identifiant (ex. `id_ingredient`, `id_categorie`, ...).
4. Créer la relation **N‑N** dans la table d’association correspondante :
   - `produit_categorie` (produit ↔ catégories)
   - `produit_ingredient` (produit ↔ ingrédients)
   - `produit_allergene` (produit ↔ allergènes)
   - `produit_label` (produit ↔ labels)
   - `produit_pays` (produit ↔ pays)

Lors de l’insertion dans ces tables d’association, le script utilise également `ON CONFLICT DO NOTHING`. Comme la clé primaire est **composite** (`code_produit`, `id_xxx`), on évite naturellement les doublons de liens (par exemple l’association du même produit à la même catégorie deux fois).

### 5. Résumé du comportement vis‑à‑vis des doublons

- Les tables de référence (lookup) comme `marque`, `categorie`, `ingredient`, `pays`, `allergene`, `label` possèdent une **colonne UNIQUE** sur le nom :
  - cela garantit qu’une même entité (ex. un ingrédient) n’est pas créée plusieurs fois.
- Les tables principales `produit` et `valeurs_nutritionnelles` utilisent `ON CONFLICT DO NOTHING` sur leur clé primaire :
  - si le produit existe déjà, **il n’est pas mis à jour** par ce script.
- Les tables d’association N‑N ont des clés primaires composites (`code_produit`, `id_xxx`) et `ON CONFLICT DO NOTHING` :
  - un même lien produit↔entité ne peut pas être dupliqué.

### 6. Comment rejouer ou adapter le chargement

- Pour tester le pipeline sans alimenter la base :

  ```bash
  python database/queries/load_data.py --source data/gold/dataset_nettoyer.csv --dry-run
  ```

- Pour charger vers une autre base ou un autre utilisateur, adapter simplement l’URL :

  ```bash
  python database/queries/load_data.py --source data/gold/dataset_nettoyer.csv --db-url "postgresql://mon_user:mon_mot_de_passe@localhost:5432/ma_base"
  ```

- Si, à l’avenir, vous souhaitez que les produits existants soient **mis à jour** (et pas seulement ignorés), il faudra modifier les requêtes SQL dans [database/queries/load_data.py](../queries/load_data.py) pour remplacer `ON CONFLICT DO NOTHING` par `ON CONFLICT (code_produit) DO UPDATE SET ...` avec la liste des colonnes à mettre à jour.



