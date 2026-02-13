from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Integer, BigInteger, Text

Base = declarative_base()

class Product(Base):
    __tablename__ = "produit"

    code_produit = Column(BigInteger, primary_key=True)

    nom_produit = Column(Text)
    quantite = Column(Text)

    nutrition_grade = Column(String)
    nutriscore_score = Column(Integer)
    nova_group = Column(Integer)

    url = Column(Text)

    image_url = Column(Text)
    image_small_url = Column(Text)
    image_ingredients_url = Column(Text)
    image_ingredients_small_url = Column(Text)
    image_nutrition_url = Column(Text)

    id_marque = Column(Integer)
