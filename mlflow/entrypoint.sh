#!/usr/bin/env bash
set -euo pipefail

# --- Ensure required directories exist (including sqlite backend path) ---
if [[ "$BACKEND_URI" == sqlite:* ]]; then
  db_path="${BACKEND_URI#sqlite:////}"
  mkdir -p "$(dirname "$db_path")" || true
fi
mkdir -p "$ARTIFACT_ROOT" "$LOG_DIR"
: > "$ACCESS_LOG_FILE" || true
: > "$ERROR_LOG_FILE" || true

# --- Build Gunicorn options: daemonize + file outputs + log level ---
# Note: when running as a daemon, logging to "-" (stdout) is not recommended.
GUNICORN_OPTS="--daemon --log-level ${GUNICORN_LOG_LEVEL} \
               --access-logfile ${ACCESS_LOG_FILE} \
               --error-logfile ${ERROR_LOG_FILE}"

# 1) Start the MLflow Tracking server (UI included) as a daemon via Gunicorn
mlflow server \
  --backend-store-uri "$BACKEND_URI" \
  --default-artifact-root "file://$ARTIFACT_ROOT" \
  --host 0.0.0.0 \
  --port "$TRACKING_PORT" \
  --gunicorn-opts "$GUNICORN_OPTS"

# Point the CLI to this tracking server
export MLFLOW_TRACKING_URI="http://$TRACKING_HOST:$TRACKING_PORT"

# 2) Wait for the MLflow server to be ready (pure CLI probe, no embedded Python)
echo "Attente du serveur MLflow (UI) sur $MLFLOW_TRACKING_URI…"
for i in {1..60}; do
  if mlflow experiments search >/dev/null 2>&1; then
    echo "Serveur MLflow + UI prêt."
    break
  fi
  sleep 1
  if [[ $i -eq 60 ]]; then
    echo "Le serveur MLflow (UI) ne répond pas."
    echo "Consulte les logs: $ERROR_LOG_FILE"
    exit 1
  fi
done

# 3) Optional model registration (idempotent behavior depends on your backend)
# Requirements:
#   - MODEL_URI like: runs:/<run_id>/model  (or another valid MLflow model URI)
#   - MODEL_NAME: target registered model name
if [[ -n "${MODEL_URI:-}" && -n "${MODEL_NAME:-}" ]]; then
  echo "Enregistrement du modèle: $MODEL_URI -> $MODEL_NAME"

  # If REGISTER_AWAIT_SECONDS is set, wait for registration to complete
  if [[ -n "${REGISTER_AWAIT_SECONDS:-}" ]]; then
    mlflow models register -m "$MODEL_URI" -n "$MODEL_NAME" \
      --await-registration-for "$REGISTER_AWAIT_SECONDS"
  else
    mlflow models register -m "$MODEL_URI" -n "$MODEL_NAME"
  fi
else
  echo "MODEL_URI et/ou MODEL_NAME non définis → aucun enregistrement effectué."
  echo "Définis, par ex.: MODEL_URI='runs:/<run_id>/model'  MODEL_NAME='XGBoostModel'"
fi

# 4) Keep container alive and stream logs (since server runs as a daemon)
exec tail -F "$ERROR_LOG_FILE" "$ACCESS_LOG_FILE"
