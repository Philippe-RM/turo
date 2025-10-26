#!/usr/bin/env python3
import os
import sys
import json
import time
import logging
import traceback
from pathlib import Path

import ray
from ray import serve
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
import pandas as pd
import mlflow
import mlflow.pyfunc as pyfunc


def _setup_logger(model_name: str) -> logging.Logger:
    log_dir = os.getenv("SERVE_LOG_DIR", "/tmp/serve-logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"serve.{model_name}")
    level = os.getenv("SERVE_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))

    # Évite les doublons si redéployé
    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = logging.FileHandler(os.path.join(log_dir, f"{model_name}.log"))
        fh.setFormatter(fmt)
        fh.setLevel(getattr(logging, level, logging.INFO))
        logger.addHandler(fh)

        # Duplique aussi sur stdout (visible via `ray_serve.log` côté mlflow)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.setLevel(getattr(logging, level, logging.INFO))
        logger.addHandler(sh)

    return logger


@serve.deployment
class MLflowModelDeployment:
    """
    Déploiement Ray Serve qui charge un modèle MLflow (pyfunc)
    et sert:
      - GET  -> "ok" (health)
      - POST -> {"predictions": ...} à partir d'un payload JSON
    """

    def __init__(self, model_uri: str, model_name: str):
        self.model_name = model_name
        self.logger = _setup_logger(model_name)

        # S'assure que le client MLflow pointe vers le serveur Tracking HTTP
        tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
        mlflow.set_tracking_uri(tracking_uri)

        # Log contexte utile
        self.logger.info("=== Replica starting ===")
        self.logger.info("model_name=%s", model_name)
        self.logger.info("model_uri=%s", model_uri)
        self.logger.info("MLFLOW_TRACKING_URI=%s", tracking_uri)
        # versions
        try:
            import xgboost as _xgb
            self.logger.info("xgboost==%s", getattr(_xgb, "__version__", "?"))
        except Exception:
            self.logger.info("xgboost not installed")
        try:
            import sklearn as _sk
            self.logger.info("scikit-learn==%s", getattr(_sk, "__version__", "?"))
        except Exception:
            self.logger.info("scikit-learn not installed")
        self.logger.info("pandas==%s", getattr(pd, "__version__", "?"))
        self.logger.info("mlflow==%s", getattr(mlflow, "__version__", "?"))

        # Charge le modèle, avec log d'erreur isolé si ça plante
        try:
            self.model = pyfunc.load_model(model_uri)
            self.logger.info("Model loaded successfully.")
        except Exception as e:
            self.logger.error("Failed to load model: %s", e)
            self.logger.error("Stacktrace:\n%s", traceback.format_exc())
            # Renvoyer une erreur claire côté Serve (déploiement échouera, mais avec trace)
            raise

    async def __call__(self, request: Request):
        if request.method == "GET":
            return PlainTextResponse("ok")

        # POST -> prédiction
        try:
            payload = await request.json()
        except Exception as e:
            self.logger.warning("Invalid JSON body: %s", e)
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        inputs = payload.get("inputs", payload.get("instances", payload))
        try:
            if isinstance(inputs, list):
                if inputs and isinstance(inputs[0], dict):
                    df = pd.DataFrame(inputs)
                else:
                    df = pd.DataFrame(inputs)
            elif isinstance(inputs, dict):
                df = pd.DataFrame([inputs])
            else:
                self.logger.warning("Unsupported payload shape: %s", type(inputs))
                return JSONResponse({"error": "Unsupported payload shape"}, status_code=400)

            preds = self.model.predict(df)
            if hasattr(preds, "tolist"):
                preds = preds.tolist()

            # Log léger (taille entrée/sortie)
            try:
                nin = len(df)
            except Exception:
                nin = "?"
            nout = len(preds) if isinstance(preds, list) else "?"
            self.logger.debug("Prediction done: n_inputs=%s n_outputs=%s", nin, nout)

            return JSONResponse({"predictions": preds})
        except Exception as e:
            self.logger.error("Prediction failed: %s", e)
            self.logger.error("Stacktrace:\n%s", traceback.format_exc())
            return JSONResponse({"error": str(e)}, status_code=500)


def main():
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        print("Usage: serve_with_ray.py /path/to/models_to_serve.json", file=sys.stderr)
        sys.exit(2)
    specs = json.load(open(sys.argv[1]))

    address = os.getenv("RAY_ADDRESS", "")
    if address:
        ray.init(address=address, ignore_reinit_error=True)
    else:
        ray.init()

    http_host = os.getenv("RAY_HTTP_HOST", "0.0.0.0")
    http_port = int(os.getenv("RAY_HTTP_PORT", "8000"))
    http_location = os.getenv("RAY_HTTP_LOCATION", "HeadOnly")

    # Toujours attacher le client Serve (même si Serve est déjà lancé côté head)
    serve.start(detached=True, http_options={"host": http_host, "port": http_port, "location": http_location})
    print(f"[Ray Serve] Attached to HTTP proxy at http://{http_host}:{http_port}", flush=True)

    # Env "de base" poussé dans les réplicas
    base_env = {
        "MLFLOW_TRACKING_URI": os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
        "SERVE_LOG_DIR": os.getenv("SERVE_LOG_DIR", "/tmp/serve-logs"),
        "SERVE_LOG_LEVEL": os.getenv("SERVE_LOG_LEVEL", "INFO"),
    }
    # (optionnel) installer des deps pip côté réplicas si l'image ray est minimale
    default_pip = os.getenv("RAY_RUNTIME_PIP_DEFAULT", "mlflow,pandas,scikit-learn")
    pip_reqs = [pkg.strip() for pkg in os.getenv("RAY_RUNTIME_PIP", default_pip).split(",") if pkg.strip()]

    for spec in specs:
        name = spec["name"]
        uri = spec["uri"]
        route_prefix = spec.get("route_prefix", f"/{name}")

        env_key = name.upper().replace("-", "_")
        min_r = int(os.getenv(f"MODEL_MIN_REPLICAS__{env_key}", "1"))
        max_r = int(os.getenv(f"MODEL_MAX_REPLICAS__{env_key}", str(min_r)))
        target = float(os.getenv(f"MODEL_TARGET_QPS__{env_key}", "5"))

        # Env spécifique par modèle (utile si tu veux logger différemment)
        env_vars = dict(base_env)
        env_vars["SERVE_MODEL_NAME"] = name

        opts = {
            "name": f"mlflow_{name}",
            "ray_actor_options": {
                "runtime_env": {
                    "env_vars": env_vars,
                    "pip": pip_reqs,  # commente si déjà packagé dans l'image ray
                }
            },
        }
        if max_r > 1:
            opts["autoscaling_config"] = {
                "min_replicas": min_r,
                "max_replicas": max_r,
                "target_num_ongoing_requests_per_replica": target,
            }

        try:
            Deployment = MLflowModelDeployment.options(**opts)
            # ⬇️ on passe aussi le model_name au constructeur (pour logger correctement)
            app = Deployment.bind(uri, name)
            serve.run(app, name=f"app_{name}", route_prefix=route_prefix)
            print(f"[Ray Serve] DEPLOYED {name} at {route_prefix} (uri={uri})", flush=True)
        except Exception as e:
            # On loggue la raison de l'échec côté mlflow (stdout) pour corréler
            import traceback as _tb
            print(f"[Ray Serve][ERROR] Failed to deploy {name} at {route_prefix}: {e}", file=sys.stderr, flush=True)
            _tb.print_exc()

    # Affiche les routes effectivement exposées (utile au debug)
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://{os.getenv('SERVE_WAIT_HOST','ray')}:{http_port}/-/routes", timeout=5) as r:
            print("[Ray Serve] Routes now:", r.read().decode().strip(), flush=True)
    except Exception as e:
        print("[Ray Serve][WARN] Could not fetch routes:", e, flush=True)

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
