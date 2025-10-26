# MLflow service

The `mlflow` directory defines the image that powers the tracking server, Model Registry automation, and Ray Serve deployment.

## Container entrypoint

[`entrypoint.sh`](./entrypoint.sh) is executed when the `mlflow` service starts.  It performs the following steps:

1. Parse the comma-separated environment variables `MODEL_NAMES`, `MODEL_PATHS`, and `MODEL_PORTS`.
2. Launch the MLflow tracking server with Gunicorn, exposing Prometheus metrics and forwarding Gunicorn statistics to the StatsD exporter.
3. Execute each MLflow project defined under `mlflow/projects/<MODEL_PATH>` using `mlflow run`.
4. Register the resulting models in the MLflow Model Registry.
5. Prepare a JSON deployment manifest (`/mlflow/logs/models_to_serve.json`).
6. Connect to the Ray head node (`RAY_ADDRESS`) and deploy each registered model via [`serve_with_ray.py`](./serve_with_ray.py).

The script exits if a project path is missing or if Ray cannot be reached within the timeout period, so always check `docker compose logs mlflow` after making changes.

## Serving implementation

[`serve_with_ray.py`](./serve_with_ray.py) attaches to the Ray cluster, starts (or reuses) a Ray Serve HTTP proxy, and creates a deployment per model.  Each deployment instantiates the `MLflowModelDeployment` class, which loads the model through `mlflow.pyfunc` and exposes two endpoints:

- `GET /<model>` → returns `ok` (health check)
- `POST /<model>` → returns `{ "predictions": [...] }` for JSON payloads containing `inputs`, `instances`, or a raw list/dict

Runtime dependencies for the replicas can be customised via the `RAY_RUNTIME_PIP` environment variable.

## MLflow projects

Each subdirectory in [`projects/`](./projects) is a self-contained MLflow project.  For example, [`projects/XGBoost`](./projects/XGBoost) contains:

- `MLproject` – project definition.
- `conda.yaml` – dependency environment (used only when you execute the project outside Docker; the container already bundles requirements via `requirements.txt`).
- `train.py` – training script (uses Ray to parallelise cross-validation, logs metrics, and saves the fitted model).

To add a new project:

1. Create a new folder under `projects/` with its own `MLproject` and training code.
2. Extend `MODEL_NAMES` and `MODEL_PATHS` in `docker-compose.yml` (lists must stay aligned).
3. Rebuild the `mlflow` image (`docker compose build mlflow`) if you introduced new Python dependencies.

## Configuration summary

Important environment variables consumed by the entrypoint:

| Variable | Description |
| --- | --- |
| `MODEL_NAMES` / `MODEL_PATHS` | Comma-separated lists of experiment names and relative project directories. |
| `BACKEND_URI` | Tracking metadata database (defaults to SQLite inside the container). |
| `ARTIFACT_ROOT` | Path where model artifacts are stored (mounts to `./mlflow_artifacts`). |
| `RAY_ADDRESS` | Ray Client URI (`ray://ray:10001` by default). |
| `RAY_HTTP_HOST` / `RAY_HTTP_PORT` | HTTP proxy exposed by Ray Serve (defaults to `0.0.0.0:8000`). |
| `SERVE_RESET_ON_START` | When `true`, tears down any existing Ray Serve deployments before creating new ones. |
| `SERVE_WAIT_TIMEOUT` | Seconds to wait for Ray Serve endpoints to become ready. |

## Logs and artifacts

- Gunicorn access/error logs live under `/mlflow/logs/` and are streamed to container stdout.
- Ray Serve deployment logs are appended to `/mlflow/logs/ray_serve.log`.
- Registered model artifacts are stored under `/mlflow/artifacts/<MODEL_NAME>/` (bind-mounted to `mlflow_artifacts/`).
- Experiment runs and metrics are recorded in `/app/mlruns` (bind-mounted to `mlruns/`).

Inspect these paths directly on the host for debugging or backup purposes.
