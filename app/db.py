import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Docker: host = db (service docker-compose)
# Local: host = localhost
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://openfood:openfood@localhost:5432/openfood"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
