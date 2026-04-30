"""Définition des modèles SQLAlchemy pour la base OpenFoodFacts — schéma v3."""

from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    Float,
    ForeignKey,
    Table,
    Boolean,
    DateTime,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()


# ── Tables d'association N:N ──────────────────────────────────────

produit_categorie = Table(
    "produit_categorie",
    Base.metadata,
    Column("id_produit", Integer, ForeignKey("produit.id_produit", ondelete="CASCADE"), nullable=False),
    Column("id_categorie", Integer, ForeignKey("categorie.id_categorie", ondelete="CASCADE"), nullable=False),
    Column("niveau", Integer),
    extend_existing=True,
)

produit_trace = Table(
    "produit_trace",
    Base.metadata,
    Column("id_produit", Integer, ForeignKey("produit.id_produit", ondelete="CASCADE"), nullable=False),
    Column("id_trace", Integer, ForeignKey("trace.id_trace", ondelete="CASCADE"), nullable=False),
    extend_existing=True,
)

trace_allergene = Table(
    "trace_allergene",
    Base.metadata,
    Column("id_trace", Integer, ForeignKey("trace.id_trace", ondelete="CASCADE"), nullable=False),
    Column("id_allergene", Integer, ForeignKey("allergene.id_allergene", ondelete="CASCADE"), nullable=False),
    extend_existing=True,
)


# ── Référentiels indépendants ─────────────────────────────────────

class Marque(Base):
    __tablename__ = "marque"
    id_marque  = Column(Integer, primary_key=True)
    nom_marque = Column(Text, unique=True, nullable=False)


class Categorie(Base):
    __tablename__ = "categorie"
    id_categorie  = Column(Integer, primary_key=True)
    nom_categorie = Column(Text, unique=True, nullable=False)


class Allergene(Base):
    __tablename__ = "allergene"
    id_allergene  = Column(Integer, primary_key=True)
    nom_allergene = Column(Text, unique=True, nullable=False)


class Trace(Base):
    __tablename__ = "trace"
    id_trace  = Column(Integer, primary_key=True)
    nom_trace = Column(Text, unique=True, nullable=False)


class IngredientStandardise(Base):
    __tablename__ = "ingredient_standardise"
    id_ingredient       = Column(Integer, primary_key=True)
    nom_canonique       = Column(Text, unique=True, nullable=False)
    nom_ingredient_brut = Column(Text)


class IngredientSynonyme(Base):
    __tablename__ = "ingredient_synonyme"
    id_synonyme  = Column(Integer, primary_key=True)
    nom_synonyme = Column(Text, nullable=False)
    langue       = Column(String(2))
    id_ingredient = Column(Integer, ForeignKey("ingredient_standardise.id_ingredient", ondelete="CASCADE"), nullable=False)


# ── Produit (table centrale) ──────────────────────────────────────

class Product(Base):
    __tablename__ = "produit"

    id_produit            = Column(Integer, primary_key=True)
    code_barre            = Column(Text, unique=True)        # EAN OpenFoodFacts
    nom_produit           = Column(Text, nullable=False)
    quantite              = Column(Text)
    categorie_principale  = Column(Text)                     # texte libre [C-5]
    nutrition_grade       = Column(Text)
    nutriscore_score      = Column(Integer)
    nova_group            = Column(Integer, CheckConstraint("nova_group BETWEEN 1 AND 4"))
    url                   = Column(Text)
    image_url             = Column(Text)
    image_small_url       = Column(Text)
    image_ingredients_url = Column(Text)
    image_nutrition_url   = Column(Text)
    # Valeurs nutritionnelles intégrées directement dans produit
    energy_kcal_100g      = Column(Float)
    fat_100g              = Column(Float)
    saturated_fat_100g    = Column(Float)
    carbohydrates_100g    = Column(Float)
    sugars_100g           = Column(Float)
    fiber_100g            = Column(Float)
    proteins_100g         = Column(Float)
    salt_100g             = Column(Float)
    # FK
    id_marque = Column(Integer, ForeignKey("marque.id_marque", ondelete="SET NULL"))

    # Relations ORM
    marque      = relationship("Marque", lazy="joined")
    categories  = relationship("Categorie", secondary=produit_categorie, lazy="select")
    traces      = relationship("Trace",     secondary=produit_trace,     lazy="select")


# ── Contient (produit ↔ ingrédient) ──────────────────────────────

class Contient(Base):
    __tablename__ = "contient"
    id_contient   = Column(Integer, primary_key=True)
    id_produit    = Column(Integer, ForeignKey("produit.id_produit",                    ondelete="CASCADE"), nullable=False)
    id_ingredient = Column(Integer, ForeignKey("ingredient_standardise.id_ingredient",  ondelete="CASCADE"), nullable=False)
    ordre         = Column(Integer, nullable=False)
    niveau        = Column(Integer, nullable=False, default=1)
    pourcentage   = Column(Float)


# ── Tables admin (inchangées fonctionnellement) ───────────────────

class RejectedProductReview(Base):
    __tablename__ = "rejected_products_review"
    rejected_id    = Column(Integer, primary_key=True)
    code_produit   = Column(Text, nullable=False)
    product_name   = Column(Text)
    brands         = Column(Text)
    raw_payload    = Column(JSONB, nullable=False)
    quality_issues = Column(JSONB, nullable=False)
    source_run_id  = Column(Text)
    source_task    = Column(Text)
    import_type    = Column(Text)
    review_status  = Column(Text, nullable=False, default="pending")
    created_at     = Column(DateTime)
    updated_at     = Column(DateTime)


class ManualProductCorrection(Base):
    __tablename__ = "manual_product_corrections"
    correction_id              = Column(Integer, primary_key=True)
    rejected_id                = Column(Integer, ForeignKey("rejected_products_review.rejected_id"))
    code_produit               = Column(Text, nullable=False)
    product_name_manual        = Column(Text)
    brands_manual              = Column(Text)
    categories_manual          = Column(Text)
    categories_tags_manual     = Column(JSONB)
    categorie_principale_manual = Column(Text)
    ingredients_text_manual    = Column(Text)
    commentaire                = Column(Text)
    corrected_by               = Column(Text)
    correction_status          = Column(Text, nullable=False, default="draft")
    is_active                  = Column(Boolean, nullable=False, default=True)
    created_at                 = Column(DateTime)
    updated_at                 = Column(DateTime)
