from datetime import datetime, timedelta, timezone
import os
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowFailException


def run_ray_task_fn(**_):
    # Read ONLY from env var AIRFLOW_VAR_RAY_ADDRESS
    ray_address = os.getenv("AIRFLOW_VAR_RAY_ADDRESS")
    if not ray_address:
        raise AirflowFailException(
            "AIRFLOW_VAR_RAY_ADDRESS is not set. "
            "Example: AIRFLOW_VAR_RAY_ADDRESS=ray://ray:10001"
        )

    print(f"[ray] Using AIRFLOW_VAR_RAY_ADDRESS={ray_address}")

    try:
        import ray

        # Connect to Ray (ray://… recommended)
        ray.init(address=ray_address, namespace="airflow", ignore_reinit_error=True)
        print("[ray] Connected. Cluster resources:", ray.cluster_resources())

        @ray.remote
        def ping():
            import socket
            return f"pong from {socket.gethostname()}"

        result = ray.get(ping.remote())
        print(f"[ray] Remote ping OK: {result}")

    except Exception as e:
        print(f"[ray] ERROR: {type(e).__name__}: {e}")
        raise AirflowFailException(f"Ray connectivity test failed: {e}")
    finally:
        try:
            ray.shutdown()
        except Exception:
            pass


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    # Set retries=0 while validating Ray integration; raise later if you want
    "retries": 0,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="ray_integration",
    description="Ray connectivity check using AIRFLOW_VAR_RAY_ADDRESS only",
    start_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
    schedule=timedelta(days=1),
    catchup=False,
    default_args=default_args,
    tags=["ray"],
) as dag:
    run_ray_task = PythonOperator(
        task_id="run_ray_task",
        python_callable=run_ray_task_fn,
    )
