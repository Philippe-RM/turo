#!/usr/bin/env bash
set -euo pipefail

# Attendre que le fichier init-complete soit présent
while [ ! -f /init-data/init-complete ]; do
  echo "Waiting for init to complete..."
  sleep 1
done

: "${DB_HOST:=postgres}"
: "${DB_PORT:=5432}"

echo "[dag-processor] waiting for Postgres at $DB_HOST:$DB_PORT ..."
until nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 1
done

exec airflow dag-processor
