-- ══════════════════════════════════════════════════════════════════
-- OPENFOOD DB — Schéma relationnel corrigé
-- Niveau : Master Data Engineering
-- Corrections appliquées :
--
--  [C-1] trace_allergene restructurée — une TRACE provoque un ALLERGENE.
--        produit → produit_trace → trace → trace_allergene → allergene
--        Suppression de produit_allergene (redondant).
--        produit_trace + trace_allergene (trace → allergene).
--
--  [C-2] contient : PK corrigée — (id_produit, id_ingredient, ordre)
--        posait un problème si ordre=NULL ou si un ingrédient
--        apparaît à plusieurs niveaux. Remplacé par une PK SERIAL
--        id_contient + contrainte UNIQUE (id_produit, ordre).
--
--  [C-3] sous_ingredient : FK composite vers contient(id_produit,
--        id_ingredient) était dangereuse car non unique dans contient.
--        Remplacé par FK vers id_contient (PK propre de contient).
--
--  [C-4] ingredient_synonyme : ajout colonne langue pour mieux
--        refléter la sémantique (variante orthographique / langue).
--
--  [C-5] produit : id_categorie_principale devient une colonne TEXT
--        simple (nom de la catégorie principale) — pas besoin d'une
--        FK complète ici, la relation N:N produit_categorie suffit.
--        Évite une dépendance circulaire produit ↔ categorie.
-- ══════════════════════════════════════════════════════════════════


-- ══════════════════════════════════════════════════════════════════
-- NETTOYAGE
-- ══════════════════════════════════════════════════════════════════
DROP TABLE IF EXISTS trace_allergene        CASCADE;
DROP TABLE IF EXISTS produit_trace          CASCADE;
DROP TABLE IF EXISTS sous_ingredient        CASCADE;
DROP TABLE IF EXISTS produit_similaire       CASCADE;
DROP TABLE IF EXISTS contient               CASCADE;
DROP TABLE IF EXISTS ingredient_synonyme    CASCADE;
DROP TABLE IF EXISTS ingredient_standardise CASCADE;
DROP TABLE IF EXISTS produit_categorie      CASCADE;
DROP TABLE IF EXISTS categorie              CASCADE;
DROP TABLE IF EXISTS allergene              CASCADE;
DROP TABLE IF EXISTS trace                  CASCADE;
DROP TABLE IF EXISTS produit                CASCADE;
DROP TABLE IF EXISTS marque                 CASCADE;


-- ══════════════════════════════════════════════════════════════════
-- 1. MARQUE
--    Entité indépendante
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE marque (
    id_marque   SERIAL PRIMARY KEY,
    nom_marque  TEXT NOT NULL UNIQUE
);


-- ══════════════════════════════════════════════════════════════════
-- 2. CATEGORIE
--    Entité indépendante
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE categorie (
    id_categorie    SERIAL PRIMARY KEY,
    nom_categorie   TEXT NOT NULL UNIQUE
);


-- ══════════════════════════════════════════════════════════════════
-- 3. PRODUIT
--    Table centrale
--    [C-5] categorie_principale = TEXT (nom libre), pas FK
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE produit (
    id_produit              SERIAL PRIMARY KEY,
    code_barre              TEXT UNIQUE,            -- code EAN OpenFoodFacts
    nom_produit             TEXT NOT NULL,
    quantite                TEXT,
    categorie_principale    TEXT,                   -- [C-5] champ texte libre
    nutrition_grade         TEXT,
    nutriscore_score        INT,
    nova_group              INT CHECK (nova_group BETWEEN 1 AND 4),
    url                     TEXT,
    image_url               TEXT,
    image_small_url         TEXT,
    image_ingredients_url   TEXT,
    image_nutrition_url     TEXT,
    -- valeurs nutritionnelles pour 100g
    energy_kcal_100g        FLOAT,
    fat_100g                FLOAT,
    saturated_fat_100g      FLOAT,
    carbohydrates_100g      FLOAT,
    sugars_100g             FLOAT,
    fiber_100g              FLOAT,
    proteins_100g           FLOAT,
    salt_100g               FLOAT,
    -- FK
    id_marque               INT REFERENCES marque(id_marque) ON DELETE SET NULL
);


-- ══════════════════════════════════════════════════════════════════
-- 4. PRODUIT_CATEGORIE
--    Relation N:N produit ↔ categorie (un produit appartient à
--    plusieurs catégories hiérarchiques OpenFoodFacts)
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE produit_categorie (
    id_produit      INT NOT NULL REFERENCES produit(id_produit)     ON DELETE CASCADE,
    id_categorie    INT NOT NULL REFERENCES categorie(id_categorie) ON DELETE CASCADE,
    niveau          INT,    -- profondeur dans la hiérarchie (1 = racine)
    PRIMARY KEY (id_produit, id_categorie)
);


-- ══════════════════════════════════════════════════════════════════
-- 5. ALLERGENE
--    Référentiel des allergènes réglementaires (14 allergènes EU)
--    Exemples : gluten, lait, arachides, fruits à coque...
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE allergene (
    id_allergene    SERIAL PRIMARY KEY,
    nom_allergene   TEXT NOT NULL UNIQUE
);


-- ══════════════════════════════════════════════════════════════════
-- 6. TRACE
--    Substance pouvant être présente en traces dans le produit
--    Exemples : "noix", "sésame", "lait"...
--    C'est la TRACE qui provoque un allergène, pas le produit
--    directement.
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE trace (
    id_trace    SERIAL PRIMARY KEY,
    nom_trace   TEXT NOT NULL UNIQUE
);


-- ══════════════════════════════════════════════════════════════════
-- 7. PRODUIT_TRACE
--    Relation N:N produit ↔ trace
--    "Ce produit peut contenir des traces de..."
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE produit_trace (
    id_produit  INT NOT NULL REFERENCES produit(id_produit) ON DELETE CASCADE,
    id_trace    INT NOT NULL REFERENCES trace(id_trace)     ON DELETE CASCADE,
    PRIMARY KEY (id_produit, id_trace)
);


-- ══════════════════════════════════════════════════════════════════
-- 8. TRACE_ALLERGENE
--    Relation N:N trace ↔ allergene
--    "Cette trace provoque cet allergène"
--    Exemple : trace "noix" → allergène "fruits à coque"
--    On obtient les allergènes d'un produit via :
--      produit → produit_trace → trace → trace_allergene → allergene
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE trace_allergene (
    id_trace        INT NOT NULL REFERENCES trace(id_trace)         ON DELETE CASCADE,
    id_allergene    INT NOT NULL REFERENCES allergene(id_allergene)  ON DELETE CASCADE,
    PRIMARY KEY (id_trace, id_allergene)
);


-- ══════════════════════════════════════════════════════════════════
-- 9. INGREDIENT_STANDARDISE
--    Référentiel des ingrédients avec nom canonique normalisé
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE ingredient_standardise (
    id_ingredient   SERIAL PRIMARY KEY,
    nom_canonique   TEXT NOT NULL UNIQUE,
    nom_ingredient_brut TEXT                          -- texte original avant normalisation
);


-- ══════════════════════════════════════════════════════════════════
-- 10. INGREDIENT_SYNONYME
--     [C-4] Variantes orthographiques / linguistiques d'un ingrédient
--     Ex: "farine de blé" → "wheat flour" → "farina de trigo"
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE ingredient_synonyme (
    id_synonyme     SERIAL PRIMARY KEY,
    nom_synonyme    TEXT NOT NULL,
    langue          CHAR(2),                -- code ISO : 'fr', 'en', 'es'...
    id_ingredient   INT NOT NULL REFERENCES ingredient_standardise(id_ingredient) ON DELETE CASCADE,
    UNIQUE (nom_synonyme, langue)
);


-- ══════════════════════════════════════════════════════════════════
-- 11. CONTIENT
--     Relation produit ↔ ingredient_standardise avec attributs
--     [C-2] PK = id_contient SERIAL (plus robuste)
--           + UNIQUE (id_produit, ordre) pour garantir l'unicité
--             de la position dans la liste
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE contient (
    id_contient         SERIAL PRIMARY KEY,             -- [C-2]
    id_produit          INT NOT NULL REFERENCES produit(id_produit)                   ON DELETE CASCADE,
    id_ingredient       INT NOT NULL REFERENCES ingredient_standardise(id_ingredient) ON DELETE CASCADE,
    ordre               INT NOT NULL,                   -- position dans la liste (1=premier)
    niveau              INT NOT NULL DEFAULT 1,         -- 1=principal, 2=sous-ingrédient...
    pourcentage         FLOAT CHECK (pourcentage BETWEEN 0 AND 100),
    UNIQUE (id_produit, ordre)                          -- [C-2] un seul ingrédient par position
);


-- ══════════════════════════════════════════════════════════════════
-- 12. SOUS_INGREDIENT
--     Hiérarchie multi-niveaux des ingrédients sans récursion SQL.
--
--     Principe : deux colonnes de parent mutuellement exclusives
--       • id_contient_parent  → utilisé pour le NIVEAU 2
--                               (parent direct = ligne de contient)
--       • id_sous_parent      → utilisé pour le NIVEAU 3, 4, 5...
--                               (parent = autre ligne de sous_ingredient)
--
--     Exemple A(b1(c1,c2), b2) pour produit A50 :
--       contient         : (A50, A, ordre=1, niveau=1)
--       sous_ingredient  : (id_contient=1, NULL,  b1, ordre=1, niveau=2)
--       sous_ingredient  : (id_contient=1, NULL,  b2, ordre=2, niveau=2)
--       sous_ingredient  : (NULL, id_sous=1,       c1, ordre=1, niveau=3)
--       sous_ingredient  : (NULL, id_sous=1,       c2, ordre=2, niveau=3)
--
--     La contrainte CHECK garantit exactement un parent renseigné.
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE sous_ingredient (
    id_sous_ingredient      SERIAL PRIMARY KEY,

    -- parent de niveau 1 → pointe vers contient
    id_contient_parent      INT REFERENCES contient(id_contient) ON DELETE CASCADE,

    -- parent de niveau 2+ → pointe vers sous_ingredient
    id_sous_parent          INT REFERENCES sous_ingredient(id_sous_ingredient) ON DELETE CASCADE,

    id_ingredient_enfant    INT NOT NULL
        REFERENCES ingredient_standardise(id_ingredient) ON DELETE CASCADE,

    ordre_enfant            INT NOT NULL DEFAULT 1,
    niveau                  INT NOT NULL,

    -- contrainte : exactement UN des deux parents doit être renseigné
    CONSTRAINT chk_un_seul_parent CHECK (
        (id_contient_parent IS NOT NULL AND id_sous_parent IS NULL)
        OR
        (id_contient_parent IS NULL     AND id_sous_parent IS NOT NULL)
    )
);


-- ══════════════════════════════════════════════════════════════════
-- INDEX — performances requêtes fréquentes
-- ══════════════════════════════════════════════════════════════════
CREATE INDEX idx_produit_marque         ON produit(id_marque);
CREATE INDEX idx_produit_cat_princ      ON produit(categorie_principale);

CREATE INDEX idx_prodcat_produit        ON produit_categorie(id_produit);
CREATE INDEX idx_prodcat_categorie      ON produit_categorie(id_categorie);




CREATE INDEX idx_prod_trace_prod        ON produit_trace(id_produit);
CREATE INDEX idx_prod_trace_trace       ON produit_trace(id_trace);
CREATE INDEX idx_trace_allergene_trace  ON trace_allergene(id_trace);
CREATE INDEX idx_trace_allergene_all    ON trace_allergene(id_allergene);

CREATE INDEX idx_contient_produit       ON contient(id_produit);
CREATE INDEX idx_contient_ingredient    ON contient(id_ingredient);
CREATE INDEX idx_contient_ordre         ON contient(id_produit, ordre);

CREATE INDEX idx_synonyme_ingredient    ON ingredient_synonyme(id_ingredient);
CREATE INDEX idx_synonyme_nom           ON ingredient_synonyme(nom_synonyme);

CREATE INDEX idx_sous_contient_parent ON sous_ingredient(id_contient_parent);
CREATE INDEX idx_sous_si_parent       ON sous_ingredient(id_sous_parent);
CREATE INDEX idx_sous_enfant          ON sous_ingredient(id_ingredient_enfant);
