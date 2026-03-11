-- =====================================================
-- SUPPRESSION SI EXISTE (ordre important)
-- =====================================================

DROP TABLE IF EXISTS produit_allergene CASCADE;
DROP TABLE IF EXISTS produit_label CASCADE;
DROP TABLE IF EXISTS produit_ingredient CASCADE;
DROP TABLE IF EXISTS produit_pays CASCADE;
DROP TABLE IF EXISTS produit_categorie CASCADE;
DROP TABLE IF EXISTS valeurs_nutritionnelles CASCADE;

DROP TABLE IF EXISTS ingredient CASCADE;
DROP TABLE IF EXISTS allergene CASCADE;
DROP TABLE IF EXISTS label CASCADE;
DROP TABLE IF EXISTS pays CASCADE;
DROP TABLE IF EXISTS categorie CASCADE;
DROP TABLE IF EXISTS marque CASCADE;
DROP TABLE IF EXISTS produit CASCADE;

-- =====================================================
-- TABLES PRINCIPALES
-- =====================================================

CREATE TABLE marque (
    id_marque SERIAL PRIMARY KEY,
    brands TEXT UNIQUE NOT NULL
);

CREATE TABLE categorie (
    id_categorie SERIAL PRIMARY KEY,
    categorie TEXT NOT NULL,
    pnns_groups_1 TEXT,
    parent_id INTEGER REFERENCES categorie(id_categorie) ON DELETE SET NULL
);

CREATE TABLE pays (
    id_pays SERIAL PRIMARY KEY,
    countries_en TEXT UNIQUE NOT NULL
);

CREATE TABLE ingredient (
    id_ingredient SERIAL PRIMARY KEY,
    ingredients_nom TEXT UNIQUE NOT NULL
);

CREATE TABLE allergene (
    allergen_id SERIAL PRIMARY KEY,
    allergens TEXT UNIQUE NOT NULL
);

CREATE TABLE label (
    label_id SERIAL PRIMARY KEY,
    labels TEXT UNIQUE NOT NULL
);

-- =====================================================
-- PRODUIT
-- =====================================================

-- IMPORTANT: code_produit en TEXT pour robustesse (codes parfois non strictement numériques)
CREATE TABLE produit (
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
    image_ingredients_url TEXT,
    image_ingredients_small_url TEXT,
    image_nutrition_url TEXT,

    id_marque INTEGER REFERENCES marque(id_marque) ON DELETE SET NULL
);

-- =====================================================
-- VALEURS NUTRITIONNELLES (1-1)
-- =====================================================

CREATE TABLE valeurs_nutritionnelles (
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

CREATE TABLE produit_categorie (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    id_categorie INTEGER REFERENCES categorie(id_categorie) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, id_categorie)
);

CREATE TABLE produit_ingredient (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    id_ingredient INTEGER REFERENCES ingredient(id_ingredient) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, id_ingredient)
);

CREATE TABLE produit_pays (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    id_pays INTEGER REFERENCES pays(id_pays) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, id_pays)
);

CREATE TABLE produit_allergene (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    allergen_id INTEGER REFERENCES allergene(allergen_id) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, allergen_id)
);

CREATE TABLE produit_label (
    code_produit TEXT REFERENCES produit(code_produit) ON DELETE CASCADE,
    label_id INTEGER REFERENCES label(label_id) ON DELETE CASCADE,
    PRIMARY KEY (code_produit, label_id)
);

-- =====================================================
-- INDEX POUR PERFORMANCE (APP WEB)
-- =====================================================

CREATE INDEX idx_produit_nom ON produit(nom_produit);
CREATE INDEX idx_categorie_nom ON categorie(categorie);
CREATE INDEX idx_ingredient_nom ON ingredient(ingredients_nom);
CREATE INDEX idx_allergene_nom ON allergene(allergens);
CREATE INDEX idx_label_nom ON label(labels);
CREATE INDEX idx_marque_nom ON marque(brands);
CREATE INDEX idx_pays_nom ON pays(countries_en);
