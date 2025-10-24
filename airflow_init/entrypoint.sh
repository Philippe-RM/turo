#!/usr/bin/env bash

set -euo pipefail



: "${DB_HOST:=postgres}"
: "${DB_PORT:=5432}"
: "${AIRFLOW__DATABASE__SQL_ALCHEMY_CONN:?SQL Alchemy conn is required}"
: "${ADMIN_USERNAME:=admin}"
: "${ADMIN_PASSWORD:=admin}"
: "${ADMIN_EMAIL:=admin@example.com}"
: "${ADMIN_FIRSTNAME:=Admin}"
: "${ADMIN_LASTNAME:=User}"




DB_USER="${DB_USER:-airflow}"
DB_PASSWORD="${DB_PASSWORD:-airflow}"

echo "[init] waiting for database 'airflow' to be created..."

# Option 1: exporter le mot de passe pour tout le script
export PGPASSWORD="$DB_PASSWORD"

until psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
  -Atqc "SELECT 1 FROM pg_database WHERE datname = 'airflow';" 2>/dev/null | grep -q '^1$'; do
  echo "Waiting for database to be created"
  sleep 1
done


echo "[init] waiting for Postgres at $DB_HOST:$DB_PORT ..."
until nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 1
done
echo "[init] migrating DB ..."
airflow db migrate
echo "[init] creating admin user (idempotent) ..."
res=$(airflow users list)
echo $res

airflow users create \
  --username "$ADMIN_USERNAME" \
  --password "$ADMIN_PASSWORD" \
  --firstname "$ADMIN_FIRSTNAME" \
  --lastname "$ADMIN_LASTNAME" \
  --role Admin \
  --email "$ADMIN_EMAIL" || true
echo "[init] done."

touch /init-data/init-complete