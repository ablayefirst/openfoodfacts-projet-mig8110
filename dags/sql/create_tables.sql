-- =====================================================
-- TABLES PRINCIPALES
-- =====================================================

CREATE TABLE IF NOT EXISTS marque (
    id_marque SERIAL PRIMARY KEY,
    brands TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS categorie (
    id_categorie SERIAL PRIMARY KEY,
    categorie TEXT NOT NULL,
    pnns_groups_1 TEXT,
    parent_id INTEGER REFERENCES categorie(id_categorie) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS pays (
    id_pays SERIAL PRIMARY KEY,
    countries_en TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS ingredient (
    id_ingredient SERIAL PRIMARY KEY,
    ingredients_nom TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS allergene (
    allergen_id SERIAL PRIMARY KEY,
    allergens TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS label (
    label_id SERIAL PRIMARY KEY,
    labels TEXT UNIQUE NOT NULL
);

-- =====================================================
-- PRODUIT
-- =====================================================

CREATE TABLE IF NOT EXISTS produit (
    code_produit TEXT PRIMARY KEY,
    nom_produit TEXT NOT NULL,
    quantite TEXT,
    categorie_principale TEXT,
    nutrition_grade CHAR(1),
    nutriscore_score INTEGER,
    nova_group INTEGER,
    url TEXT,
    image_url TEXT,
    image_small_url TEXT,
    image_nutrition_url TEXT,
    id_marque INTEGER REFERENCES marque(id_marque) ON DELETE SET NULL
);

-- =====================================================
-- VALEURS NUTRITIONNELLES (1-1)
-- =====================================================

CREATE TABLE IF NOT EXISTS valeurs_nutritionnelles (
    code_produit TEXT PRIMARY KEY
        REFERENCES produit(code_produit)
        ON DELETE CASCADE,
    energy_kcal_100g NUMERIC,
    saturated_fat_100g NUMERIC,
    sugars_100g NUMERIC,
    fiber_100g NUMERIC,
    proteins_100g NUMERIC,
    salt_100g NUMERIC,
    carbohydrates_100g NUMERIC,
    fat_100g NUMERIC
);

-- =====================================================
-- TABLES D'ASSOCIATION (N-N)
-- =====================================================

CREATE TABLE IF NOT EXISTS produit_categorie (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    id_categorie INTEGER REFERENCES categorie(id_categorie) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, id_categorie)
);


CREATE TABLE IF NOT EXISTS synonyme_ingredient (
    id_synonyme SERIAL PRIMARY KEY,
    nom_synonyme TEXT,
    id_ingredient INT REFERENCES ingredient(id_ingredient),
    langue TEXT,
    source TEXT DEFAULT 'manual',
    relation_type TEXT DEFAULT 'exact',
    confidence NUMERIC(5,2),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE synonyme_ingredient
ADD COLUMN IF NOT EXISTS langue TEXT;

ALTER TABLE synonyme_ingredient
ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual';

ALTER TABLE synonyme_ingredient
ADD COLUMN IF NOT EXISTS relation_type TEXT DEFAULT 'exact';

ALTER TABLE synonyme_ingredient
ADD COLUMN IF NOT EXISTS confidence NUMERIC(5,2);

ALTER TABLE synonyme_ingredient
ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;


CREATE TABLE IF NOT EXISTS produit_ingredient (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    id_ingredient INTEGER REFERENCES ingredient(id_ingredient) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, id_ingredient)
);

CREATE TABLE IF NOT EXISTS produit_pays (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    id_pays INTEGER REFERENCES pays(id_pays) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, id_pays)
);

CREATE TABLE IF NOT EXISTS produit_allergene (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    allergen_id INTEGER REFERENCES allergene(allergen_id) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, allergen_id)
);

CREATE TABLE IF NOT EXISTS produit_label (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    label_id INTEGER REFERENCES label(label_id) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, label_id)
);

-- =====================================================
-- SUIVI TECHNIQUE DES IMPORTS
-- =====================================================

CREATE TABLE IF NOT EXISTS etl_import_history (
    import_id SERIAL PRIMARY KEY,
    import_type TEXT NOT NULL,
    bronze_key TEXT,
    silver_key TEXT,
    source_reference TEXT,
    source_start_ts BIGINT,
    source_end_ts BIGINT,
    rows_input INTEGER NOT NULL DEFAULT 0,
    rows_loaded INTEGER NOT NULL DEFAULT 0,
    imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- RECOMMANDATIONS PRODUITS
-- =====================================================

CREATE TABLE IF NOT EXISTS produit_similaire (
    code_produit_source TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    code_produit_cible TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    type_recommandation TEXT NOT NULL,
    score_similarite NUMERIC,
    nb_ingredients_communs INTEGER,
    ingredients_communs TEXT,
    methode TEXT,
    health_score_source NUMERIC,
    health_score_cible NUMERIC,
    PRIMARY KEY (code_produit_source, code_produit_cible, type_recommandation)
);

-- =====================================================
-- INDEX POUR PERFORMANCE (APP WEB + ETL)
-- =====================================================

-- Cleanup for databases created with older schema versions.
-- UNIQUE constraints already create indexes for marque, pays, ingredient,
-- allergene and label, so explicit duplicates are unnecessary.
DROP INDEX IF EXISTS idx_produit_nom;
DROP INDEX IF EXISTS idx_categorie_nom;
DROP INDEX IF EXISTS idx_ingredient_nom;
DROP INDEX IF EXISTS idx_allergene_nom;
DROP INDEX IF EXISTS idx_label_nom;
DROP INDEX IF EXISTS idx_marque_nom;
DROP INDEX IF EXISTS idx_pays_nom;

-- Trigram indexes speed up case-insensitive substring searches used by
-- Streamlit filters such as LOWER(column) LIKE LOWER('%...%').
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_produit_nom_trgm
ON produit USING gin (LOWER(nom_produit) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_categorie_nom_trgm
ON categorie USING gin (LOWER(categorie) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_produit_categorie_principale_trgm
ON produit USING gin (LOWER(COALESCE(categorie_principale, '')) gin_trgm_ops);

-- This helps nutrition-based filtering and insights aggregations.
CREATE INDEX IF NOT EXISTS idx_valeurs_nutritionnelles_sugars
ON valeurs_nutritionnelles(sugars_100g)
WHERE sugars_100g IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_etl_import_history_imported_at ON etl_import_history(imported_at);
CREATE INDEX IF NOT EXISTS idx_etl_import_history_type_end_ts ON etl_import_history(import_type, source_end_ts);
CREATE INDEX IF NOT EXISTS idx_produit_similaire_source_type
ON produit_similaire(code_produit_source, type_recommandation);

CREATE INDEX IF NOT EXISTS idx_synonyme_ingredient_id_ingredient
ON synonyme_ingredient(id_ingredient);

CREATE INDEX IF NOT EXISTS idx_synonyme_ingredient_nom_trgm
ON synonyme_ingredient USING gin (LOWER(COALESCE(nom_synonyme, '')) gin_trgm_ops);

CREATE UNIQUE INDEX IF NOT EXISTS idx_synonyme_ingredient_nom_unique
ON synonyme_ingredient(LOWER(TRIM(nom_synonyme)))
WHERE nom_synonyme IS NOT NULL AND TRIM(nom_synonyme) <> '';

CREATE OR REPLACE VIEW ingredient_lookup AS
SELECT
    i.id_ingredient,
    i.ingredients_nom AS nom_recherche,
    LOWER(TRIM(i.ingredients_nom)) AS nom_recherche_normalise,
    i.ingredients_nom AS nom_canonique,
    'ingredient' AS source,
    'exact' AS relation_type
FROM ingredient i
WHERE i.ingredients_nom IS NOT NULL AND TRIM(i.ingredients_nom) <> ''

UNION ALL

SELECT
    s.id_ingredient,
    s.nom_synonyme AS nom_recherche,
    LOWER(TRIM(s.nom_synonyme)) AS nom_recherche_normalise,
    i.ingredients_nom AS nom_canonique,
    COALESCE(NULLIF(TRIM(s.source), ''), 'synonyme') AS source,
    COALESCE(NULLIF(TRIM(s.relation_type), ''), 'exact') AS relation_type
FROM synonyme_ingredient s
JOIN ingredient i ON i.id_ingredient = s.id_ingredient
WHERE s.nom_synonyme IS NOT NULL AND TRIM(s.nom_synonyme) <> '';
