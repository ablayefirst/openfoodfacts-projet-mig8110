import os
import psycopg2


def get_connection():
    """
    Returns a PostgreSQL connection using Docker environment variables.
    Defaults match docker-compose configuration.
    """
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        dbname=os.getenv("POSTGRES_DB", "openfood_db"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres123"),
        port=os.getenv("POSTGRES_PORT", "5432"),
    )
    return conn