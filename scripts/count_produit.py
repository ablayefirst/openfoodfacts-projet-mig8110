#!/usr/bin/env python3
from sqlalchemy import create_engine, text
import sys

DB_URL = "postgresql://postgres:admin@localhost:5432/openfoodfacts_canada"

# Script pour compter le nombre de produits dans la table "produit"
def main():
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        res = conn.execute(text("SELECT COUNT(*) FROM produit;"))
        count = res.scalar()
        print(count)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
