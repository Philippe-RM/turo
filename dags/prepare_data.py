from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd
import os

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2025, 10, 26),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'prepare_data',
    default_args=default_args,
    description='A DAG to prepare data from reservations and vehicles CSV files',
    schedule=None,
)

def load_data(**kwargs):
    # Charger les données à partir des fichiers CSV
    reservations = pd.read_csv('/app/datas/reservations.csv')
    vehicles = pd.read_csv('/app/datas/vehicles.csv')
    # Pousser les DataFrames dans XCom pour les tâches suivantes
    kwargs['ti'].xcom_push(key='reservations', value=reservations.to_json())
    kwargs['ti'].xcom_push(key='vehicles', value=vehicles.to_json())

def process_data(**kwargs):
    # Récupérer les données des tâches précédentes
    ti = kwargs['ti']
    reservations_json = ti.xcom_pull(task_ids='load_data', key='reservations')
    vehicles_json = ti.xcom_pull(task_ids='load_data', key='vehicles')
    reservations = pd.read_json(reservations_json)
    vehicles = pd.read_json(vehicles_json)

    # Calculer la cible (par exemple, le nombre de réservations par véhicule)
    target = reservations.groupby('vehicle_id').size().reset_index(name='target')

    # Fusionner les données
    merged_data = pd.merge(vehicles, target, on='vehicle_id', how='left')

    # Sauvegarder les données traitées dans XCom
    kwargs['ti'].xcom_push(key='processed_data', value=merged_data.to_json())

def save_data(**kwargs):
    # Récupérer les données traitées
    ti = kwargs['ti']
    processed_data_json = ti.xcom_pull(task_ids='process_data', key='processed_data')
    processed_data = pd.read_json(processed_data_json)

    # Sauvegarder les données dans un nouveau fichier CSV
    output_path = '/app/datas/datas.csv'
    processed_data.to_csv(output_path, index=False)

    # Log the output path
    print(f"Data saved to {output_path}")

with dag:
    load_data_task = PythonOperator(
        task_id='load_data',
        python_callable=load_data,
    )

    process_data_task = PythonOperator(
        task_id='process_data',
        python_callable=process_data,
    )

    save_data_task = PythonOperator(
        task_id='save_data',
        python_callable=save_data,
    )

    load_data_task >> process_data_task >> save_data_task
