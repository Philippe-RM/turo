#!/usr/bin/env bash
set -euo pipefail

# Définir le séparateur
IFS=', ' read -r -a MODEL_NAMES <<< "${MODEL_NAMES}"
IFS=', ' read -r -a MODEL_PATHS <<< "${MODEL_PATHS}"
IFS=', ' read -r -a MODEL_PORTS <<< "${MODEL_PORTS}"

# Ensure required directories exist (including sqlite backend path)
if [[ "$BACKEND_URI" == sqlite:* ]]; then
  db_path="${BACKEND_URI#sqlite:////}"
  mkdir -p "$(dirname "$db_path")" || true
fi

# Create directories for each model
for i in "${!MODEL_NAMES[@]}"; do
  model_name=${MODEL_NAMES[$i]}
  model_path=${MODEL_PATHS[$i]}
  # Assurez-vous que le chemin est relatif à PROJECT_DIR
  full_model_path="$PROJECT_DIR/$model_path"
  mkdir -p "$ARTIFACT_ROOT/$model_name" "$LOG_DIR/$model_name"
  : > "$LOG_DIR/$model_name/access.log" || true
  : > "$LOG_DIR/$model_name/error.log" || true
done

# Build Gunicorn options: daemonize + file outputs + log level
GUNICORN_OPTS="--daemon --log-level ${GUNICORN_LOG_LEVEL} \
               --access-logfile ${ACCESS_LOG_FILE} \
               --error-logfile ${ERROR_LOG_FILE} \
               --workers 4 \
               --statsd-host=statsd-exporter:9125 \
               --statsd-prefix=mlflow "

# Start the MLflow Tracking server (includes the UI) as a daemon via Gunicorn
mlflow server --expose-prometheus "/mlflow-metrics" \
  --backend-store-uri "$BACKEND_URI" \
  --default-artifact-root "file://$ARTIFACT_ROOT" \
  --host 0.0.0.0 \
  --port "$TRACKING_PORT" \
  --gunicorn-opts "$GUNICORN_OPTS"

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

# Get or create the Experiment and retrieve its ID for each model
for i in "${!MODEL_NAMES[@]}"; do
  model_name=${MODEL_NAMES[$i]}
  model_path=${MODEL_PATHS[$i]}
  model_port=${MODEL_PORTS[$i]}
  full_model_path="$PROJECT_DIR/$model_path"
  EXPERIMENT_ID=$(python - <<PY
import os, mlflow
name = "${model_name}"
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
  echo "Experiment: $model_name (id=$EXPERIMENT_ID)"

  # Run the MLflow project for each model
  if [[ ! -f "$full_model_path/MLproject" ]]; then
    echo "ERREUR: fichier MLproject introuvable à l’emplacement: $full_model_path"
    exit 1
  fi
  echo "Exécution du projet: $full_model_path"
  mlflow run "$full_model_path" --experiment-id "$EXPERIMENT_ID" --env-manager local --run-name "${model_name}_run"

  # Fetch the latest FINISHED run that contains a 'model' artifact for each model
  RUN_ID=$(python - <<PY
import os, mlflow
client = mlflow.MlflowClient()
exp_id = "$EXPERIMENT_ID"
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
  echo "RUN_ID for $model_name: $RUN_ID"

  # Serve the model in the background
  if [[ -n "${RUN_ID:-}" ]]; then
    echo "Serving modèle $model_name du run: $RUN_ID sur le port $model_port"
    mlflow models serve -m "runs:/$RUN_ID/model" \
         --env-manager local --host 0.0.0.0 -p "$model_port" &
  else
    echo "Aucun run terminé avec un artefact 'model' n’a été trouvé pour $model_name."
  fi
done

# Keep container alive by tailing logs
echo "Le serveur MLflow (UI incluse) tourne en arrière-plan. Suivi des logs…"
exec tail -F "$ERROR_LOG_FILE" "$ACCESS_LOG_FILE"
