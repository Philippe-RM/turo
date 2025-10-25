#!/usr/bin/env bash
set -Eeuo pipefail

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }

# --- Defaults (override via env vars) ---
: "${AIRFLOW_UI_BASE_URL:=http://airflow_api-server:8080}"    # UI base (not /api)
: "${AIRFLOW_API_PREFIX:=/api/v2}"                             # /api/v1 on 3.0.x (3.1+ uses /api/v2)
: "${DAG_IDS:=}"                                               # e.g. "example_dag,my_etl"
: "${ITEST_TIMEOUT:=600}"                                      # max time to wait for SUCCESS (seconds)
: "${ITEST_POLL_EVERY:=5}"                                     # polling interval (seconds)
: "${WAIT_API_TIMEOUT:=180}"                                   # /health wait timeout (seconds)
: "${EXTRA_PYTEST_ARGS:=}"                                     # extra pytest flags
: "${JUNIT_XML_PATH:=}"                                        # e.g. /app/itests-report/junit.xml

# --- Sanity checks ---
if [[ -z "$DAG_IDS" ]]; then
  echo "❌ Required env var DAG_IDS is missing (e.g., DAG_IDS=\"example_dag\")."
  exit 2
fi

# --- Wait until the API is ready (/health without auth) ---
log "Waiting for Airflow API at ${AIRFLOW_UI_BASE_URL}${AIRFLOW_API_PREFIX}/monitor/health ..."
deadline=$((SECONDS + WAIT_API_TIMEOUT))
until curl -fsS "${AIRFLOW_UI_BASE_URL}${AIRFLOW_API_PREFIX}/monitor/health" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "❌ API not ready after ${WAIT_API_TIMEOUT}s (${AIRFLOW_UI_BASE_URL}${AIRFLOW_API_PREFIX}/monitor/health)."
    exit 1
  fi
  sleep 2
done
log "✅ API /health OK."

# --- Obtain a Bearer token if not provided ---
# If AIRFLOW_BEARER_TOKEN is empty AND AIRFLOW_USERNAME/PASSWORD are provided,
# request a token via POST /auth/token (FabAuthManager).
if [[ -z "${AIRFLOW_BEARER_TOKEN:-}" ]] && [[ -n "${AIRFLOW_USERNAME:-}" ]] && [[ -n "${AIRFLOW_PASSWORD:-}" ]]; then
  log "Fetching Bearer token from /auth/token for user '${AIRFLOW_USERNAME}' ..."
  TOKEN_OUT="$(python - <<'PY'
import os, sys, httpx
ui = os.environ["AIRFLOW_UI_BASE_URL"].rstrip("/")
u  = os.environ["AIRFLOW_USERNAME"]
p  = os.environ["AIRFLOW_PASSWORD"]
try:
    r = httpx.post(f"{ui}/auth/token", json={"username": u, "password": p}, timeout=30)
    r.raise_for_status()
    print(r.json()["access_token"])
except Exception as e:
    print(f"ERR:{e}", file=sys.stderr); sys.exit(1)
PY
)" || true

  if [[ "$TOKEN_OUT" == ERR:* || -z "$TOKEN_OUT" ]]; then
    echo "❌ Failed to obtain token via /auth/token."
    exit 1
  fi
  export AIRFLOW_BEARER_TOKEN="$TOKEN_OUT"
  log "🔐 Token acquired."
fi

# --- Export variables used by pytest tests ---
export AIRFLOW_API_BASE_URL="${AIRFLOW_UI_BASE_URL%/}${AIRFLOW_API_PREFIX}"
export DAG_IDS ITEST_TIMEOUT ITEST_POLL_EVERY AIRFLOW_BEARER_TOKEN

# --- Build the pytest command ---
PYTEST_CMD=(pytest -q /app/tests )
if [[ -n "$JUNIT_XML_PATH" ]]; then
  PYTEST_CMD+=("--junitxml=$JUNIT_XML_PATH")
fi
if [[ -n "$EXTRA_PYTEST_ARGS" ]]; then
  # shellcheck disable=SC2206
  EXTRA_ARR=($EXTRA_PYTEST_ARGS)
  PYTEST_CMD+=("${EXTRA_ARR[@]}")
fi

log "Starting tests: ${PYTEST_CMD[*]}"

echo ${PYTEST_CMD[@]}
exec "${PYTEST_CMD[@]}"
