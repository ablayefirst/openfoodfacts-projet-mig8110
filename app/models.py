from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Integer

Base = declarative_base()

class Product(Base):
    __tablename__ = "products"   # <-- change ici si ton binôme a un autre nom

    code = Column(String, primary_key=True, index=True)
    product_name = Column(String)
    brands = Column(String)
    categories = Column(String)
    categories_tags = Column(String)
    allergens_tags = Column(String)
    nutriscore_grade = Column(String)    # correspond à off:nutriscore_grade
    nutriscore_score = Column(Integer)   # correspond à off:nutriscore_score
    ingredients_text = Column(String)
