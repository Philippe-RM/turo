#!/usr/bin/env bash
set -euo pipefail

while [ ! -f /init-data/init-complete ]; do echo "Waiting for init"; sleep 1; done 

: "${DB_HOST:=postgres}"
: "${DB_PORT:=5432}"

echo "[webserver] waiting for Postgres at $DB_HOST:$DB_PORT ..."
until nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 1
done

# airflow db upgrade || true
exec airflow api-server
