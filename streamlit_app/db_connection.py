import os
import psycopg2
from psycopg2 import OperationalError


def get_connection():
    host = os.getenv("POSTGRES_HOST", "postgres")
    dbname = os.getenv("POSTGRES_DB", "openfood_db")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres123")
    port = os.getenv("POSTGRES_PORT", "5432")

    try:
        connection = psycopg2.connect(
            host=host,
            dbname=dbname,
            user=user,
            password=password,
            port=port,
        )

        print("✅ Database connection successful.")
        return connection

    except OperationalError as error:
        print("❌ Failed to connect to PostgreSQL.")
        print(f"Details: {error}")
        raise