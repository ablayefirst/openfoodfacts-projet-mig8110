import os
import psycopg2
from psycopg2 import OperationalError


def get_connection():
    """
    Crée et retourne une connexion PostgreSQL via psycopg2.
    Utilise les variables d'environnement du docker-compose.

    Utilise psycopg2 (v2) pour être compatible avec pandas.read_sql()
    sans avertissement, et cohérent avec db.py (SQLAlchemy).
    """

    host     = os.getenv("POSTGRES_HOST",     "postgres")
    dbname   = os.getenv("POSTGRES_DB",       "openfood_db")
    user     = os.getenv("POSTGRES_USER",     "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres123")
    port     = os.getenv("POSTGRES_PORT",     "5432")

    try:
        connection = psycopg2.connect(
            host=host,
            dbname=dbname,
            user=user,
            password=password,
            port=port,
        )
        # CORRECTION point 10 : suppression du print qui spammait les logs Docker
        return connection

    except OperationalError as error:
        raise
