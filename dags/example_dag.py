from datetime import datetime, timedelta, timezone
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    # (optionnel mais recommandé) date de début timezone-aware
    "start_date": datetime(2023, 1, 1, tzinfo=timezone.utc),
    "email": ["your_email@example.com"],
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

def print_hello():
    print("Hello from Airflow!")

with DAG(
    dag_id="example_dag",
    description="Un exemple de DAG",
    default_args=default_args,
    schedule=timedelta(days=1),  # ou "@daily", "0 0 * * *", etc.
    catchup=False,               # évite le rattrapage depuis 2023
) as dag:
    start = EmptyOperator(task_id="start")
    hello_task = PythonOperator(task_id="hello_task", python_callable=print_hello)
    end = EmptyOperator(task_id="end")

    start >> hello_task >> end
