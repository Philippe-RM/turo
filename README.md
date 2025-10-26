# Turo Analytics Platform

## Overview
This repository defines a containerised analytics platform that connects Apache Airflow, MLflow, Ray, and a full monitoring stack.  It is designed to orchestrate data preparation workflows, train and register models, and serve predictions through Ray Serve.  Supporting services (PostgreSQL, Redis, Prometheus, Grafana, Jupyter) are bundled so the entire stack can be started with Docker Compose.

## Contents

- [Overview](#overview)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Data & shared volumes](#data--shared-volumes)
- [Airflow](#airflow)
- [MLflow & model serving](#mlflow--model-serving)
- [Ray cluster](#ray-cluster)
- [Notebooks](#notebooks)
- [Monitoring & metrics](#monitoring--metrics)
- [Testing compose file locally](#testing-compose-file-locally)
- [Extending the platform](#extending-the-platform)
- [Troubleshooting](#troubleshooting)
- [Further reading](#further-reading)

The default configuration focuses on an end-to-end reservation forecasting use case:

1. **Data preparation** – Combine vehicle and reservation datasets to produce engineered features.
2. **Model training** – Launch MLflow projects for XGBoost, SVR, CatBoost, and KNN inside Airflow tasks.
3. **Model registration & serving** – Publish models to the MLflow Model Registry and expose REST endpoints via Ray Serve.

All services share volumes inside this repository (`datas/`, `mlflow_artifacts/`, `mlruns/`, etc.), which makes it easy to inspect outputs while containers are running.

## Repository layout

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | Main composition file for the complete stack. |
| `airflow_*` | Docker build contexts for the different Airflow components (webserver/API, scheduler, workers, triggerer, dag processor). |
| `dags/` | Airflow DAG definitions, including the Ray-enabled training pipeline. |
| `datas/` | Example CSV inputs and the generated training dataset (`datas.csv`). |
| `mlflow/` | MLflow tracking server image, Ray Serve bootstrapper, and packaged MLflow projects. |
| `mlflow/projects/` | Individual MLflow projects for each model family (CatBoost, KNN, SVR, XGBoost). |
| `ray/` | Ray head node image used by Airflow and MLflow. |
| `jupyter/` | Notebook environment that mounts the shared datasets and MLflow artifacts. |
| `prometheus/`, `grafana/`, `statsd-exporter/` | Monitoring stack configuration. |
| `refresh.sh` | Utility script to rebuild and restart every container from scratch (clears existing volumes). |

## Prerequisites

- Docker 24+
- Docker Compose v2 plugin (`docker compose` CLI)
- At least 8 GB RAM available for the containers (Ray + Airflow + MLflow)
- Optional: `make` (if you want to add helper commands)

## Quick start

1. Clone this repository and open a terminal in the project root (`turo/`).
2. Build the images:
   ```bash
   docker compose build
   ```
3. Start the stack in the background:
   ```bash
   docker compose up -d
   ```
4. Wait until the Airflow API container initialises the database (watch with `docker compose logs -f airflow_init`).
5. Log in to the web UIs (default credentials `admin` / `admin` unless noted otherwise):
   - Airflow: http://localhost:8080
   - MLflow Tracking UI: http://localhost:5000
   - Ray Dashboard: http://localhost:8265
   - Ray Serve endpoints: http://localhost:8000
   - Prometheus: http://localhost:9090
   - Grafana: http://localhost:3000 (first login forces you to change the password)
   - JupyterLab: http://localhost:8888 (token printed in container logs)

Shut everything down with `docker compose down` (add `-v` to delete bound volumes).

> **Tip:** The `refresh.sh` script resets every container and volume before rebuilding. It is destructive and assumes Linux/macOS paths in the repository.

## Data & shared volumes

The default DAGs expect the following files inside `datas/`:

- `reservations.csv` – Raw reservation data.
- `vehicles.csv` – Vehicle catalogue.
- `datas.csv` – Generated training table (created by the `prepare_data` DAG).

These files, along with MLflow artifacts (`mlflow_artifacts/`) and run metadata (`mlruns/`), are mounted inside the relevant containers so that Airflow tasks, MLflow projects, and Ray Serve replicas read and write to the same host directories.

## Airflow

Airflow is split into multiple services as defined in `docker-compose.yml`:

- `airflow_api-server` – Combines the classic webserver UI and the execution API.
- `airflow_scheduler`, `airflow-worker`, `airflow-triggerer`, `airflow_dag-processor` – Background processes required by the Celery executor.
- `airflow_init` – One-off bootstrap container that creates the admin account, database schema, and Airflow variables.

The containers share `dags/` so that any new DAG file is picked up automatically. Default admin credentials (`admin` / `admin`) and database settings are configured through environment variables in the compose file.

### Built-in DAGs

See `dags/README.md` for detailed descriptions. Highlights:

- **`prepare_data`** – Orchestrates data preparation, distributed aggregation with Ray, MLflow project training, and registry registration.
- **`ray_integration`** – Sanity-check DAG that verifies Airflow can connect to the Ray cluster using the `AIRFLOW_VAR_RAY_ADDRESS` environment variable.
- **`example_dag`** – Minimal example showing the baseline Airflow structure.

### Ray connectivity from Airflow

Airflow tasks that use Ray read the cluster address from the environment variable `AIRFLOW_VAR_RAY_ADDRESS`. The default `.env` baked into the containers points to the `ray` service (`ray://ray:10001`). If you deploy workers on other hosts, update this variable in the Airflow UI (`Admin > Variables`).

## MLflow & model serving

The `mlflow` service performs several roles on start-up (`mlflow/entrypoint.sh`):

1. Launch the MLflow tracking server via Gunicorn (`mlflow server --serve-artifacts`) and expose Prometheus metrics to the monitoring stack.
2. Execute each MLflow project found in `mlflow/projects/` for the configured model names (comma-separated lists in `MODEL_NAMES` and `MODEL_PATHS`).
3. Register the resulting runs in the MLflow Model Registry.
4. Generate a deployment specification consumed by `serve_with_ray.py` and push the models to Ray Serve (HTTP proxy on port 8000).

Key environment variables (see `docker-compose.yml` for defaults):

- `MODEL_NAMES`, `MODEL_PATHS` – Parallel lists of experiments/projects that should be executed and served.
- `TRACKING_PORT`, `TRACKING_BIND_HOST`, `TRACKING_PUBLIC_HOST` – How the tracking server is exposed.
- `BACKEND_URI` – Metadata store (SQLite by default inside the container).
- `ARTIFACT_ROOT` – Directory that stores model artifacts (mounted from `mlflow_artifacts/`).
- `RAY_ADDRESS`, `RAY_HTTP_HOST`, `RAY_HTTP_PORT` – Connection details for the Ray cluster and Ray Serve proxy.

Each project is a standard MLflow project (see `mlflow/README.md` for details). Modify `train.py`, `conda.yaml`, or project parameters to experiment with your own models.

### Accessing served models

Ray Serve exposes one route per model (default `/<MODEL_NAME>`). A simple curl example:

```bash
curl -X POST http://localhost:8000/XGBoost \
  -H 'Content-Type: application/json' \
  -d '{"inputs": [{"feature_1": 0.1, "feature_2": 2.3, "feature_3": 5}]}'
```

Responses look like `{"predictions": [123.45]}`. Check the MLflow container logs for Ray Serve deployment status.

## Ray cluster

The `ray` service runs a Ray head node (`ray/entrypoint.sh`) and starts a Ray Serve controller with the HTTP proxy bound to `0.0.0.0:8000`. Key ports:

- 6380 – GCS/head TCP port
- 10001 – Ray Client protocol used by Airflow and MLflow
- 8265 – Ray dashboard
- 8000 – Ray Serve HTTP gateway

Adjust resource limits, runtime dependencies, or serve behaviour inside `ray/Dockerfile` and `ray/entrypoint.sh`.

## Notebooks

The `jupyter` service launches JupyterLab (`http://localhost:8888`) with the repository’s `datas/`, `mlruns/`, and other volumes mounted under `/notebooks`. Use it to explore datasets, inspect MLflow artifacts, or test Ray Serve endpoints interactively.

## Monitoring & metrics

- **Prometheus** (port 9090) scrapes MLflow (via `/mlflow-metrics`), Ray, and StatsD exporter metrics.
- **StatsD exporter** (port 9102) receives Gunicorn metrics from the MLflow tracking server (`--statsd-host=statsd-exporter:9125`).
- **Grafana** (port 3000) loads dashboards from `grafana/provisioning/dashboards/json/` on startup. Default credentials: `admin` / `admin`.

Add more dashboards or scrape targets by editing the configuration files in `prometheus/` or `grafana/`.

## Testing compose file locally

A lightweight compose file (`docker-compose.test.yml`) is provided for CI. It includes only the services necessary to run integration tests (Airflow API, Postgres, Redis). Use it as a template if you want to run headless pipelines without Ray, MLflow, or monitoring.

## Extending the platform

- **Add new Airflow DAGs** by dropping Python files into `dags/`.
- **Register additional MLflow projects** by adding a folder under `mlflow/projects/` and updating the `MODEL_NAMES`/`MODEL_PATHS` environment variables in `docker-compose.yml`.
- **Scale Ray** by attaching worker nodes to the head node (see [Ray docs](https://docs.ray.io)).
- **Customise monitoring** through Prometheus scrape configs and Grafana dashboard provisioning.

## Troubleshooting

- Run `docker compose logs -f <service>` to inspect container output.
- Ensure ports 5000, 8000, 8080, 8265, 8888, 9090, and 3000 are free on your host.
- If Ray Serve endpoints are not responding, verify the `ray` container is healthy and that the MLflow service finished deploying models (look for `[Ray Serve] DEPLOYED` messages).
- Delete stale volumes with `docker compose down -v` if the MLflow database or artifacts contain outdated state.

## Further reading

- [Airflow DAG reference](dags/README.md)
- [MLflow service internals](mlflow/README.md)
- [Ray head node behaviour](ray/README.md)
- [JupyterLab workspace usage](jupyter/README.md)
- [CI/CD workflow and integration tests](.github/workflows/README.md)

Happy experimenting!
