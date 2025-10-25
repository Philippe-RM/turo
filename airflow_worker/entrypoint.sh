#!/usr/bin/env bash
set -euo pipefail

# attendre la fin de l'init
while [ ! -f /init-data/init-complete ]; do
  echo "[worker] Waiting for init"; sleep 1
done

: "${DB_HOST:=postgres}"
: "${DB_PORT:=5432}"
: "${REDIS_HOST:=redis}"
: "${REDIS_PORT:=6379}"
: "${EXEC_API_HOST:=airflow_api-server}"
: "${EXEC_API_PORT:=8080}"

echo "[worker] waiting for Postgres at $DB_HOST:$DB_PORT ..."
until nc -z "$DB_HOST" "$DB_PORT"; do sleep 1; done

echo "[worker] waiting for Redis at $REDIS_HOST:$REDIS_PORT ..."
until nc -z "$REDIS_HOST" "$REDIS_PORT"; do sleep 1; done

echo "[worker] waiting for Execution API at $EXEC_API_HOST:$EXEC_API_PORT ..."
until nc -z "$EXEC_API_HOST" "$EXEC_API_PORT"; do sleep 1; done

# Démarre le worker Celery d'Airflow (prefork par défaut)
exec airflow celery worker
# Pour limiter/concurrencer par env:
# AIRFLOW__CELERY__WORKER_CONCURRENCY=4
# AIRFLOW__CELERY__WORKER_PREFETCH_MULTIPLIER=1
