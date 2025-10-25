#!/usr/bin/env bash
set -euo pipefail

# Ensure required directories exist (including sqlite backend path)
# (The MLflow Tracking server started below serves the UI as well.)
if [[ "$BACKEND_URI" == sqlite:* ]]; then
  db_path="${BACKEND_URI#sqlite:////}"
  mkdir -p "$(dirname "$db_path")" || true
fi
mkdir -p "$ARTIFACT_ROOT" "$LOG_DIR"
: > "$ACCESS_LOG_FILE" || true
: > "$ERROR_LOG_FILE" || true

# Build Gunicorn options: daemonize + file outputs + log level
# Note: when running as a daemon, logging to "-" (stdout) is not recommended.
GUNICORN_OPTS="--daemon --log-level ${GUNICORN_LOG_LEVEL} \
               --access-logfile ${ACCESS_LOG_FILE} \
               --error-logfile ${ERROR_LOG_FILE} \
               --workers 4 \
               --statsd-host=statsd-exporter:9125 \
               --statsd-prefix=mlflow "

# ——————————————————————————————
# 1) Start the MLflow Tracking server (includes the UI) as a daemon via Gunicorn
# ——————————————————————————————
mlflow server --expose-prometheus "/mlflow-metrics" \
  --backend-store-uri "$BACKEND_URI" \
  --default-artifact-root "file://$ARTIFACT_ROOT" \
  --host 0.0.0.0 \
  --port "$TRACKING_PORT" \
  --gunicorn-opts "$GUNICORN_OPTS" \
  
  

export MLFLOW_TRACKING_URI="http://$TRACKING_HOST:$TRACKING_PORT"

# Wait for MLflow server/UI to be ready (probe via Python API)
echo "Attente du serveur MLflow (UI) sur $MLFLOW_TRACKING_URI…"
for i in {1..60}; do
  if python - <<'PY'
import os, sys, mlflow
try:
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    from mlflow.tracking import MlflowClient
    MlflowClient().search_experiments()  # succeeds when server & UI app are up
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
  then
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

# ——————————————————————————————
# 2) Get or create the Experiment and retrieve its ID
# ——————————————————————————————
EXPERIMENT_ID=$(python - <<'PY'
import os, mlflow
name = os.environ.get("EXPERIMENT_NAME","XGBoost_Experiment")
art_root = os.environ.get("ARTIFACT_ROOT","/mlflow/artifacts").rstrip("/")
client = mlflow.MlflowClient()
exp = client.get_experiment_by_name(name)
if exp is None:
    eid = client.create_experiment(name, artifact_location=f"file://{art_root}/{name}")
else:
    eid = exp.experiment_id
print(eid)
PY
)
export EXPERIMENT_ID

echo "Experiment: $EXPERIMENT_NAME (id=$EXPERIMENT_ID)"

# ——————————————————————————————
# 3) Run the MLflow project (no Conda in image -> use local env manager)
# ——————————————————————————————
if [[ ! -f "$PROJECT_DIR/MLproject" ]]; then
  echo "ERREUR: fichier MLproject introuvable à l’emplacement: $PROJECT_DIR"
  exit 1
fi

echo "Exécution du projet: $PROJECT_DIR"
mlflow run "$PROJECT_DIR" --experiment-id "$EXPERIMENT_ID" --env-manager local

# ——————————————————————————————
# 4) Fetch the latest FINISHED run that contains a 'model' artifact
# ——————————————————————————————
RUN_ID=$(python - <<'PY'
import os, mlflow
client = mlflow.MlflowClient()
exp_id = os.environ["EXPERIMENT_ID"]
runs = client.search_runs([exp_id], order_by=["attributes.start_time DESC"], max_results=50)
for r in runs:
    if r.info.status == "FINISHED":
        try:
            client.list_artifacts(r.info.run_id, "model")
            print(r.info.run_id)
            break
        except Exception:
            continue
PY
)

# ——————————————————————————————
# 5) Serve the model (blocking) or keep container alive by tailing logs
# ——————————————————————————————
if [[ -n "${RUN_ID:-}" ]]; then
  echo "Serving modèle du run: $RUN_ID"
  exec mlflow models serve -m "runs:/$RUN_ID/model" \
       --env-manager local --host 0.0.0.0 -p "$MODEL_PORT"
else
  echo "Aucun run terminé avec un artefact 'model' n’a été trouvé."
  echo "Le serveur MLflow (UI incluse) tourne en arrière-plan. Suivi des logs…"
  exec tail -F "$ERROR_LOG_FILE" "$ACCESS_LOG_FILE"
fi
