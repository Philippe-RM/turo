# Ray head node

The `ray` service supplies a Ray cluster that Airflow tasks, MLflow projects, and Ray Serve replicas connect to.

## Runtime behaviour

[`entrypoint.sh`](./entrypoint.sh) executes when the container starts:

1. Launches a Ray head node with:
   - Client port `10001`
   - GCS/head port `6380`
   - Dashboard on `8265`
   - Ray Serve HTTP proxy bound to `0.0.0.0:8000`
2. Starts Ray Serve in detached mode so that MLflow can deploy models without starting a new proxy.
3. Monitors the Raylet and Serve logs (`tail -F /tmp/ray/session_latest/logs/...`).

All metrics and logs are available through the Ray dashboard and the Prometheus scrape targets defined in `docker-compose.yml`.

## Connecting external workers

To scale the cluster beyond the single head node:

1. Start a new container or VM with the same Ray version.
2. Run `ray start --address='ray-head-host:6380' --ray-client-server-port=10001` (adjust host/IP as needed).
3. Ensure the worker can resolve `mlflow` and other service hostnames if you expect it to load models or data from shared volumes.

Airflow uses the environment variable `AIRFLOW_VAR_RAY_ADDRESS` (default `ray://ray:10001`) to connect.  Update this variable if you expose Ray on a different address.

## Installing additional packages

The base image installs dependencies from [`requirements.txt`](./requirements.txt).  If your Ray tasks require extra libraries, add them there and rebuild the image:

```bash
docker compose build ray
```

For quick experiments you can also rely on runtime environments (see `ray.runtime_env` in Ray documentation), but baking requirements into the image keeps worker environments consistent.
