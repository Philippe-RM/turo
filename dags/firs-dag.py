from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator

# Définir les arguments par défaut pour le DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2023, 1, 1),
    'email': ['your_email@example.com'],
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Définir le DAG
dag = DAG(
    'example_dag',
    default_args=default_args,
    description='Un exemple de DAG',
    schedule_interval=timedelta(days=1),
)

# Définir une fonction pour une tâche Python
def print_hello():
    print("Hello from Airflow!")

# Définir les tâches
start = EmptyOperator(task_id='start', dag=dag)
hello_task = PythonOperator(
    task_id='hello_task',
    python_callable=print_hello,
    dag=dag,
)
end = EmptyOperator(task_id='end', dag=dag)

# Définir les dépendances entre les tâches
start >> hello_task >> end
