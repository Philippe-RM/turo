#!/bin/bash
set -euo pipefail

# 1) Démarrer le cluster Ray (head)
ray start --head --port=6380 --ray-client-server-port=10001 --dashboard-port=8265

# 2) Démarrer le proxy HTTP de Ray Serve (0.0.0.0:8000 sur le head)
python - <<'PY'
import time, urllib.request
import ray
from ray import serve

ray.init(address="auto", ignore_reinit_error=True)

# Démarre (ou connecte) Serve avec les bonnes options HTTP sur le head
serve.start(
    detached=True,
    http_options={"host": "0.0.0.0", "port": 8000, "location": "HeadOnly"},
)
print("[ray-head] Serve HTTP proxy started on 0.0.0.0:8000", flush=True)

# Petit wait pour la santé HTTP
deadline = time.time() + 30
while time.time() < deadline:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/-/healthz", timeout=1) as r:
            print("[ray-head] /-/healthz:", r.read().decode().strip(), flush=True)
            break
    except Exception:
        time.sleep(0.5)
else:
    print("[ray-head][WARN] Serve HTTP not reachable on 127.0.0.1:8000 yet", flush=True)
PY

# 3) Suivre les logs Ray / Serve
tail -F /tmp/ray/session_latest/logs/raylet.out /tmp/ray/session_latest/logs/serve*.log
