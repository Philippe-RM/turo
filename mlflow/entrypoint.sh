#!/usr/bin/env bash
set -euo pipefail

# ---------- Parsing des variables d'env (listes séparées par virgules) ----------
IFS=', ' read -r -a MODEL_NAMES <<< "${MODEL_NAMES}"
IFS=', ' read -r -a MODEL_PATHS <<< "${MODEL_PATHS}"
IFS=', ' read -r -a MODEL_PORTS <<< "${MODEL_PORTS}"  # (non utilisé avec Ray Serve, conservé pour compat/env)

# ---------- Defaults utiles ----------
: "${LOG_DIR:=/mlflow/logs}"
: "${ARTIFACT_ROOT:=/mlflow/artifacts}"
: "${PROJECT_DIR:=/app/projects}"
: "${GUNICORN_LOG_LEVEL:=info}"

# Séparer le host de bind et le host "public" (résolution réseau inter-conteneurs)
: "${TRACKING_BIND_HOST:=0.0.0.0}"
: "${TRACKING_PUBLIC_HOST:=mlflow}"
: "${TRACKING_PORT:=5000}"

: "${ACCESS_LOG_FILE:=$LOG_DIR/mlflow_access.log}"
: "${ERROR_LOG_FILE:=$LOG_DIR/mlflow_error.log}"

# ----- Ray cluster externe -----
# IMPORTANT: on cible le cluster 'ray' (DNS du head) et on force le proxy HTTP Serve sur le head
: "${RAY_ADDRESS:=ray://ray:10001}"
: "${RAY_HTTP_HOST:=0.0.0.0}"
: "${RAY_HTTP_PORT:=8000}"
: "${RAY_HTTP_LOCATION:=HeadOnly}"   # HeadOnly = proxy HTTP unique sur le head

# Reset Serve au démarrage (utile si un Serve résiduel tourne déjà dans le cluster)
: "${SERVE_RESET_ON_START:=true}"

# Attente/Pré-chauffage des endpoints Serve
: "${SERVE_WAIT_HOST:=ray}"
: "${SERVE_WAIT_TIMEOUT:=180}"

# ----- Emplacements scripts -----
: "${SERVE_SCRIPT_PATH:=/app/serve_with_ray.py}"
SERVE_SPECS_FILE="$LOG_DIR/models_to_serve.json"

# ---------- Préparation des répertoires ----------
mkdir -p "$LOG_DIR" "$ARTIFACT_ROOT"

# ---------- Backend MLflow (sqlite) ----------
if [[ "${BACKEND_URI}" == sqlite:* ]]; then
  db_path="${BACKEND_URI#sqlite:////}"
  mkdir -p "$(dirname "$db_path")" || true
fi

# ---------- Prépare les répertoires par modèle ----------
for i in "${!MODEL_NAMES[@]}"; do
  model_name=${MODEL_NAMES[$i]}
  model_path=${MODEL_PATHS[$i]}
  full_model_path="$PROJECT_DIR/$model_path"

  mkdir -p "$ARTIFACT_ROOT/$model_name" "$LOG_DIR/$model_name"
  : > "$LOG_DIR/$model_name/access.log" || true
  : > "$LOG_DIR/$model_name/error.log" || true

  if [[ ! -d "$full_model_path" ]]; then
    echo "ERREUR: chemin du projet MLflow introuvable: $full_model_path"
    exit 1
  fi
done

# ---------- Démarre le serveur MLflow (UI incluse) via Gunicorn ----------
GUNICORN_OPTS="--daemon --log-level ${GUNICORN_LOG_LEVEL} \
               --access-logfile ${ACCESS_LOG_FILE} \
               --error-logfile ${ERROR_LOG_FILE} \
               --workers 4 \
               --statsd-host=statsd-exporter:9125 \
               --statsd-prefix=mlflow "

mlflow server --expose-prometheus "/mlflow-metrics" \
  --backend-store-uri "$BACKEND_URI" \
  --default-artifact-root "file://$ARTIFACT_ROOT" \
  --serve-artifacts \
  --host "$TRACKING_BIND_HOST" \
  --port "$TRACKING_PORT" \
  --gunicorn-opts "$GUNICORN_OPTS"

# L'URI que doivent utiliser tous les clients (y compris les réplicas Ray)
export MLFLOW_TRACKING_URI="http://${TRACKING_PUBLIC_HOST}:${TRACKING_PORT}"

# ---------- Attente de disponibilité du serveur MLflow ----------
echo "Attente du serveur MLflow (UI) sur $MLFLOW_TRACKING_URI…"
for i in {1..60}; do
  if python - <<'PY'
import os, sys, mlflow
try:
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    from mlflow.tracking import MlflowClient
    MlflowClient().search_experiments()  # OK si server+UI up
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

# ---------- Initialisation du fichier de specs pour Ray Serve ----------
echo "[]" > "$SERVE_SPECS_FILE"

# ---------- Exécution des projets MLflow + collecte des modèles à servir ----------
ALL_OK=true
for i in "${!MODEL_NAMES[@]}"; do
  model_name=${MODEL_NAMES[$i]}
  model_path=${MODEL_PATHS[$i]}
  full_model_path="$PROJECT_DIR/$model_path"

  # Crée / récupère l'Experiment pour ce modèle
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

  # Vérifie la présence d'un MLproject
  if [[ ! -f "$full_model_path/MLproject" ]]; then
    echo "ERREUR: fichier MLproject introuvable à l’emplacement: $full_model_path"
    ALL_OK=false
    continue
  fi

  echo "Exécution du projet: $full_model_path"
  if ! mlflow run "$full_model_path" --experiment-id "$EXPERIMENT_ID" --env-manager local --run-name "${model_name}_run"; then
    echo "ERREUR: exécution du projet MLflow échouée pour $model_name"
    ALL_OK=false
    continue
  fi

  # Récupère le dernier run FINISHED qui contient un artefact 'model'
  RUN_ID=$(python - <<PY
import os, mlflow
client = mlflow.MlflowClient()
exp_id = "$EXPERIMENT_ID"
runs = client.search_runs([exp_id], order_by=["attributes.start_time DESC"], max_results=100)
for r in runs:
    if r.info.status == "FINISHED":
        try:
            client.list_artifacts(r.info.run_id, "model")  # raises if missing
            print(r.info.run_id)
            break
        except Exception:
            continue
PY
)
  echo "RUN_ID pour $model_name: ${RUN_ID:-<none>}"

  # Ajoute ce modèle au fichier de déploiement Ray Serve
  if [[ -n "${RUN_ID:-}" ]]; then
    MODEL_URI="runs:/$RUN_ID/model"
    echo "Ajout du modèle $model_name -> $MODEL_URI pour Ray Serve"
    python - "$SERVE_SPECS_FILE" <<PY
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data.append({"name": "${model_name}", "uri": "${MODEL_URI}", "route_prefix": "/${model_name}"})
json.dump(data, open(path, "w"))
PY





  echo "Enregistrement de ${model_name} depuis ${MODEL_URI} dans la Registry…"
  python - <<PY
import mlflow
from mlflow.tracking import MlflowClient

name = "${model_name}"
uri  = "${MODEL_URI}"
client = MlflowClient()

# Crée le Registered Model s'il n'existe pas
try:
    client.get_registered_model(name)
except Exception:
    client.create_registered_model(name)

# Enregistre une nouvelle version depuis le run
mv = mlflow.register_model(model_uri=uri, name=name)
print(f"RegisteredModel: {name} v{mv.version} (source: {uri})")

# (optionnel) Transition en Staging et archive les précédentes
client.transition_model_version_stage(
    name=name,
    version=mv.version,
    stage="Staging",
    archive_existing_versions=True
)
print(f"Transitioned {name} v{mv.version} -> Staging")
PY








  else
    echo "Aucun run terminé avec un artefact 'model' n’a été trouvé pour $model_name."
    ALL_OK=false
  fi
done

# Petit affichage de contrôle
echo "Contenu de $SERVE_SPECS_FILE :"
cat "$SERVE_SPECS_FILE" || true

# ---------- Attente du cluster Ray (mode cluster) ----------
if [[ -n "${RAY_ADDRESS:-}" ]]; then
  echo "Attente du cluster Ray à ${RAY_ADDRESS}…"
  for i in {1..60}; do
    if python - <<'PY'
import os, sys, ray
addr = os.environ.get("RAY_ADDRESS")
try:
    ray.init(address=addr, ignore_reinit_error=True)
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
    then
      echo "Cluster Ray joignable."
      break
    fi
    sleep 1
    if [[ $i -eq 60 ]]; then
      echo "Le cluster Ray n'est pas joignable à ${RAY_ADDRESS}."
      exit 1
    fi
  done
fi

# ---------- Reset optionnel de Serve dans le cluster ----------
if [[ "${SERVE_RESET_ON_START}" == "true" || "${SERVE_RESET_ON_START}" == "1" ]]; then
  echo "Reset de Ray Serve dans le cluster…"
  python - <<'PY'
import os, ray
from ray import serve
addr = os.environ.get("RAY_ADDRESS")
ray.init(address=addr, ignore_reinit_error=True)
try:
    serve.shutdown()
    print("Serve reset: previous controller/proxy shut down.")
except Exception as e:
    print(f"No existing Serve to shutdown (ok): {e}")
PY
fi

# ---------- Lancement de Ray Serve (dans le cluster) ----------
if [[ ! -f "$SERVE_SCRIPT_PATH" ]]; then
  echo "ERREUR: script Ray Serve introuvable à $SERVE_SCRIPT_PATH"
  exit 1
fi

echo "Démarrage de Ray Serve (proxy HTTP dans le cluster) sur ${RAY_HTTP_HOST}:${RAY_HTTP_PORT}…"
# Variables passées à serve_with_ray.py via l'env
export RAY_ADDRESS RAY_HTTP_HOST RAY_HTTP_PORT RAY_HTTP_LOCATION
# Très important : transmettre l'URI public MLflow aux réplicas via serve_with_ray.py
export MLFLOW_TRACKING_URI

python "$SERVE_SCRIPT_PATH" "$SERVE_SPECS_FILE" >> "$LOG_DIR/ray_serve.log" 2>&1 &

echo "Ray Serve lancé. Endpoints (préfixes) attendus:"
python - "$SERVE_SPECS_FILE" <<'PY'
import json, sys
specs = json.load(open(sys.argv[1]))
for s in specs:
    rp = s.get('route_prefix','/'+s['name'])
    print(f" - {rp}")
if not specs:
    print(" (aucun modèle déployé)")
PY

# ---------- Attente de readiness des endpoints Ray Serve ----------
echo "Attente des endpoints Ray Serve sur http://${SERVE_WAIT_HOST}:${RAY_HTTP_PORT}… (timeout=${SERVE_WAIT_TIMEOUT}s)"
python - <<PY
import os, time, json, urllib.request
host = os.getenv("SERVE_WAIT_HOST", "ray")
port = os.getenv("RAY_HTTP_PORT", "8000")
base = f"http://{host}:{port}"
specs = json.load(open("${SERVE_SPECS_FILE}"))
deadline = time.time() + int(os.getenv("SERVE_WAIT_TIMEOUT", "180"))
pending = {s["name"]: f'{base}{s.get("route_prefix","/"+s["name"])}' for s in specs}

while pending and time.time() < deadline:
    for name, url in list(pending.items()):
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status < 400 and resp.read().decode().strip().lower() == "ok":
                    print(f"[ready] {name} at {url}", flush=True)
                    del pending[name]
        except Exception:
            pass
    time.sleep(1)

if pending:
    print(f"[warn] Endpoints not ready before timeout: {pending}", flush=True)
else:
    print("[ok] Tous les endpoints Ray Serve sont prêts.", flush=True)
PY

# ---------- Keep-alive + suivi des logs ----------
echo "Le serveur MLflow (UI incluse) tourne en arrière-plan. Suivi des logs…"
exec tail -F "$ERROR_LOG_FILE" "$ACCESS_LOG_FILE" "$LOG_DIR/ray_serve.log"
