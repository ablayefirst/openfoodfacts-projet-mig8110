"""Définition des modèles SQLAlchemy pour la base OpenFoodFacts."""

from sqlalchemy.orm import declarative_base, relationship, column_property
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    ForeignKey,
    Table,
    select,
    func,
    Numeric,
    DateTime,
)
from sqlalchemy.dialects.postgresql import JSONB

# Base commune à tous les modèles ORM
Base = declarative_base()


# Tables d'association pour les relations N-N (produit-catégorie, produit-ingrédient, produit-allergène)
produit_categorie = Table(
    "produit_categorie",
    Base.metadata,
    Column("code_produit", Text),
    Column("id_categorie", Integer),
    extend_existing=True,
)

produit_ingredient = Table(
    "produit_ingredient",
    Base.metadata,
    Column("code_produit", Text),
    Column("id_ingredient", Integer),
    extend_existing=True,
)

produit_allergene = Table(
    "produit_allergene",
    Base.metadata,
    Column("code_produit", Text),
    Column("allergen_id", Integer),
    extend_existing=True,
)


class Marque(Base):
    """Table des marques, une ligne par marque unique."""
    __tablename__ = "marque"
    id_marque = Column(Integer, primary_key=True)
    brands = Column(Text, unique=True, nullable=False)


class Categorie(Base):
    """Table des catégories de produits (ex: snacks, boissons)."""
    __tablename__ = "categorie"
    id_categorie = Column(Integer, primary_key=True)
    categorie = Column(Text, nullable=False)


class Ingredient(Base):
    """Table des ingrédients distincts (libellé texte)."""
    __tablename__ = "ingredient"
    id_ingredient = Column(Integer, primary_key=True)
    ingredients_nom = Column(Text, unique=True, nullable=False)


class Allergene(Base):
    """Table des allergènes distincts (gluten, lait, etc.)."""
    __tablename__ = "allergene"
    allergen_id = Column(Integer, primary_key=True)
    allergens = Column(Text, unique=True, nullable=False)


class ValeursNutritionnelles(Base):
    """Table 1-1 contenant les valeurs nutritionnelles par code produit."""
    __tablename__ = "valeurs_nutritionnelles"
    code_produit = Column(Text, primary_key=True)
    energy_kcal_100g = Column(Numeric)
    saturated_fat_100g = Column(Numeric)
    sugars_100g = Column(Numeric)
    fiber_100g = Column(Numeric)
    proteins_100g = Column(Numeric)
    salt_100g = Column(Numeric)
    carbohydrates_100g = Column(Numeric)
    fat_100g = Column(Numeric)



class RejectedProductReview(Base):
    """Produits rejetés par le pipeline et en attente de revue manuelle."""
    __tablename__ = "rejected_products_review"

    rejected_id = Column(Integer, primary_key=True)
    code_produit = Column(Text, nullable=False)
    product_name = Column(Text)
    brands = Column(Text)
    raw_payload = Column(JSONB, nullable=False)
    quality_issues = Column(JSONB, nullable=False)
    source_run_id = Column(Text)
    source_task = Column(Text)
    import_type = Column(Text)
    review_status = Column(Text, nullable=False, default="pending")
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class ProductCategorySuggestion(Base):
    """Suggestion automatique de catégorie validable par l'utilisateur."""
    __tablename__ = "product_category_suggestions"

    suggestion_id = Column(Integer, primary_key=True)
    rejected_id = Column(Integer, ForeignKey("rejected_products_review.rejected_id"))
    code_produit = Column(Text, nullable=False)
    suggested_categories = Column(Text)
    suggested_categories_tags = Column(JSONB)
    suggested_categorie_principale = Column(Text)
    suggestion_source = Column(Text, nullable=False)
    suggestion_confidence = Column(Numeric(5, 2))
    decision_status = Column(Text, nullable=False, default="suggested")
    validated_by = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class Product(Base):
    """Table principale des produits avec liens vers marques, catégories, ingrédients, allergènes."""
    __tablename__ = "produit"
    code_produit = Column(Text, primary_key=True)
    nom_produit = Column(Text)
    quantite = Column(Text)
    nutrition_grade = Column(String(1))
    nutriscore_score = Column(Integer)
    nova_group = Column(Integer)
    url = Column(Text)
    image_url = Column(Text)
    image_small_url = Column(Text)
    image_nutrition_url = Column(Text)
    id_marque = Column(Integer, ForeignKey("marque.id_marque"))
    marque = relationship("Marque", lazy="joined")

    # Propriété calculée pour récupérer le libellé de la marque à partir de l'id_marque
    brands = column_property(
        select(Marque.brands)
        .where(Marque.id_marque == id_marque)
        .scalar_subquery()
    )

    # Propriétés calculées pour agréger catégories, ingrédients et allergènes liés au produit
    categories = column_property(
        select(func.coalesce(func.string_agg(Categorie.categorie, ' | '), ''))
        .select_from(produit_categorie.join(Categorie, produit_categorie.c.id_categorie == Categorie.id_categorie))
        .where(produit_categorie.c.code_produit == code_produit)
        .scalar_subquery()
    )
    categories_tags = column_property(categories)
    ingredients_text = column_property(
        select(func.coalesce(func.string_agg(Ingredient.ingredients_nom, ' | '), ''))
        .select_from(produit_ingredient.join(Ingredient, produit_ingredient.c.id_ingredient == Ingredient.id_ingredient))
        .where(produit_ingredient.c.code_produit == code_produit)
        .scalar_subquery()
    )
    allergens_tags = column_property(
        select(func.coalesce(func.string_agg(Allergene.allergens, ' | '), ''))
        .select_from(produit_allergene.join(Allergene, produit_allergene.c.allergen_id == Allergene.allergen_id))
        .where(produit_allergene.c.code_produit == code_produit)
        .scalar_subquery()
    )

    # Propriétés calculées pour exposer les valeurs nutritionnelles comme si elles étaient des colonnes directes
    energy_kcal_100g = column_property(
        select(ValeursNutritionnelles.energy_kcal_100g)
        .where(ValeursNutritionnelles.code_produit == code_produit)
        .scalar_subquery()
    )
    fat_100g = column_property(
        select(ValeursNutritionnelles.fat_100g)
        .where(ValeursNutritionnelles.code_produit == code_produit)
        .scalar_subquery()
    )
    saturated_fat_100g = column_property(
        select(ValeursNutritionnelles.saturated_fat_100g)
        .where(ValeursNutritionnelles.code_produit == code_produit)
        .scalar_subquery()
    )
    sugars_100g = column_property(
        select(ValeursNutritionnelles.sugars_100g)
        .where(ValeursNutritionnelles.code_produit == code_produit)
        .scalar_subquery()
    )
    fiber_100g = column_property(
        select(ValeursNutritionnelles.fiber_100g)
        .where(ValeursNutritionnelles.code_produit == code_produit)
        .scalar_subquery()
    )
    proteins_100g = column_property(
        select(ValeursNutritionnelles.proteins_100g)
        .where(ValeursNutritionnelles.code_produit == code_produit)
        .scalar_subquery()
    )
    salt_100g = column_property(
        select(ValeursNutritionnelles.salt_100g)
        .where(ValeursNutritionnelles.code_produit == code_produit)
        .scalar_subquery()
    )
    carbohydrates_100g = column_property(
        select(ValeursNutritionnelles.carbohydrates_100g)
        .where(ValeursNutritionnelles.code_produit == code_produit)
        .scalar_subquery()
    )
