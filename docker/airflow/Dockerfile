FROM apache/airflow:2.8.1-python3.11

USER root

# Installation des dépendances système nécessaires
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libssl-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Copie des requirements spécifiques à Airflow
COPY docker/airflow/requirements.txt /tmp/requirements.txt

# Installation des dépendances Python
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Création des dossiers nécessaires
RUN mkdir -p /opt/airflow/scripts \
             /opt/airflow/data \
             /opt/airflow/config \
             /opt/airflow/logs

WORKDIR /opt/airflow
