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
