FROM apache/airflow:3.0.6

WORKDIR /app

USER root
# utilitaire 'nc' pour wait-for
RUN apt-get update && apt-get install -y --no-install-recommends netcat-openbsd \
  && rm -rf /var/lib/apt/lists/*
USER airflow

# Dépendances Python projet (facultatif)
COPY requirements.txt /requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -s /requirements.txt ]; then pip install --no-cache-dir -r /requirements.txt; fi

ENV AIRFLOW_HOME=/opt/airflow
WORKDIR ${AIRFLOW_HOME}
