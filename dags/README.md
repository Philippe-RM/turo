# Airflow DAGs

This directory contains the workflows that orchestrate the reservation analytics demo.  All DAGs are mounted into every Airflow container via `docker-compose.yml`, so editing a file here automatically reloads the pipeline inside the UI.

## `prepare_data`

Comprehensive orchestration pipeline defined in [`tain_model.py`](./tain_model.py):

1. **Input validation** – Verifies that `datas/reservations.csv` and `datas/vehicles.csv` exist.
2. **Reservation aggregation** – Uses Ray to aggregate reservation counts per vehicle.  Falls back to pandas if Ray is unreachable.
3. **Vehicle merge** – Joins the aggregate back onto `vehicles.csv` and normalises the results.
4. **Feature selection** – Computes Pearson correlations to select significant numeric features and writes the final dataset to `datas/datas.csv` (the training target column is called `target`).
5. **Model specification** – Builds a list of MLflow projects to run.  Model names and relative paths are taken from the `MODEL_NAMES`/`MODEL_PATHS` environment variables provided by the Docker Compose file.
6. **Model training** – Dynamically maps over the model specifications.  Each task launches `mlflow run` against the project path, using the Airflow container’s Python interpreter.  Metrics and artifacts are logged to the shared MLflow tracking server.
7. **Model registration** – After a successful run completes, the DAG waits for the MLflow run to finish and registers (or updates) the model inside the Model Registry.  Optional `REGISTER_STAGE` and `REGISTER_WAIT_SECS` variables control promotion behaviour.

The DAG is unscheduled (`schedule=None`) so you can trigger it manually from the Airflow UI.  It requires the Ray and MLflow services to be running.

## `ray_integration`

Connectivity test defined in [`ray_integration.py`](./ray_integration.py).  It reads the Ray cluster address from `AIRFLOW_VAR_RAY_ADDRESS`, initialises a Ray client session, and executes a simple remote function.  Use it to validate networking and authentication whenever you change Ray deployment settings.

## `example_dag`

Small example defined in [`example_dag.py`](./example_dag.py) that illustrates the project structure.  Feel free to delete or replace it with your own experiments.

## Developing new DAGs

1. Create a new Python module in this directory.
2. Ensure the module defines a DAG object named `dag` or uses the `@dag` decorator.
3. Restart the Airflow scheduler or wait for the next DAG parsing cycle (approx. every 30 seconds) for it to appear in the UI.
4. Keep dependencies lightweight—the containers already include Ray, MLflow, pandas, and scikit-learn.  If you need additional libraries, extend the appropriate Dockerfiles under `airflow_*`.

Airflow configuration snippets worth knowing:

- **Variables:** manage under `Admin → Variables`.  Ray address, MLflow host, and dataset paths can be overridden without rebuilding images.
- **Connections:** set up under `Admin → Connections` if you integrate with external data stores.
- **Logs:** stored in the `logs/` volume created by `airflow_worker` (bind-mount at runtime).
