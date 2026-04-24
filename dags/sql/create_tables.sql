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
    id_ingredient INT REFERENCES ingredient(id_ingredient)
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
-- REVUE DES PRODUITS REJETES ET SUGGESTIONS DE CATEGORIES
-- =====================================================

CREATE TABLE IF NOT EXISTS rejected_products_review (
    rejected_id SERIAL PRIMARY KEY,
    code_produit TEXT NOT NULL,
    product_name TEXT,
    brands TEXT,
    raw_payload JSONB NOT NULL,
    quality_issues JSONB NOT NULL,
    source_run_id TEXT,
    source_task TEXT,
    import_type TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'suggested', 'validated', 'resolved', 'ignored', 'needs_review')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE rejected_products_review
DROP CONSTRAINT IF EXISTS rejected_products_review_review_status_check;

ALTER TABLE rejected_products_review
ADD CONSTRAINT rejected_products_review_review_status_check
CHECK (review_status IN ('pending', 'suggested', 'validated', 'resolved', 'ignored', 'needs_review'));

CREATE TABLE IF NOT EXISTS product_category_suggestions (
    suggestion_id SERIAL PRIMARY KEY,
    rejected_id INTEGER NOT NULL REFERENCES rejected_products_review(rejected_id) ON DELETE CASCADE,
    code_produit TEXT NOT NULL,
    suggested_categories TEXT,
    suggested_categories_tags JSONB,
    suggested_categorie_principale TEXT,
    suggestion_source TEXT NOT NULL,
    suggestion_confidence NUMERIC(5,2),
    decision_status TEXT NOT NULL DEFAULT 'suggested'
        CHECK (decision_status IN ('suggested', 'validated', 'rejected', 'needs_review', 'applied')),
    validated_by TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    mode_sante TEXT,
    health_score_source NUMERIC,
    health_score_cible NUMERIC,
    PRIMARY KEY (code_produit_source, code_produit_cible, type_recommandation)
);

ALTER TABLE produit_similaire ADD COLUMN IF NOT EXISTS mode_sante TEXT;

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
CREATE INDEX IF NOT EXISTS idx_rejected_products_review_code
ON rejected_products_review(code_produit);
CREATE INDEX IF NOT EXISTS idx_rejected_products_review_status
ON rejected_products_review(review_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_product_category_suggestions_code
ON product_category_suggestions(code_produit);
CREATE INDEX IF NOT EXISTS idx_product_category_suggestions_status
ON product_category_suggestions(decision_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_product_category_suggestions_rejected_id
ON product_category_suggestions(rejected_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_category_suggestions_active
ON product_category_suggestions(rejected_id)
WHERE decision_status IN ('suggested', 'validated', 'needs_review');
CREATE INDEX IF NOT EXISTS idx_produit_similaire_source_type
ON produit_similaire(code_produit_source, type_recommandation);
