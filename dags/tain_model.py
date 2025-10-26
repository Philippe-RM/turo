from __future__ import annotations
import os
import sys
import subprocess
from functools import reduce

import numpy as np
import pandas as pd
import ray

from airflow.decorators import dag, task, task_group
from airflow.utils import timezone
from airflow.exceptions import AirflowSkipException

# ---------------------------------------------------------------------
# ENV / Paramètres (peuvent être fournis via Docker/Compose/K8S/Env)
# ---------------------------------------------------------------------
PROJECT_DIR = os.getenv("PROJECT_DIR", "/app/projects")
TRACKING_HOST = os.getenv("TRACKING_HOST", "127.0.0.1")
TRACKING_PORT = os.getenv("TRACKING_PORT", "5000")
MODEL_NAMES = os.getenv("MODEL_NAMES", "XGBoost0, XGBoost1, XGBoost2")
MODEL_PATHS = os.getenv("MODEL_PATHS", "XGBoost0, XGBoost1, XGBoost2")

# ---- Chemins demandés ----
INPUT_RESERVATIONS = "/app/datas/reservations.csv"
INPUT_VEHICLES = "/app/datas/vehicles.csv"
OUTPUT_DATASET = "/app/datas/datas.csv"
# Fichiers temporaires
TMP_AGG = "/tmp/agg_reservations.csv"
TMP_MERGED = "/tmp/merged_vehicles_reservations.csv"


default_args = {
    "owner": "data-eng",
    "depends_on_past": False,
    "retries": 0,
}


# ---------------------------------------------------------------------
# Utils Ray
# ---------------------------------------------------------------------
def _ray_init():
    """
    Initialise Ray en se basant sur la variable d'environnement RAY_ADDRESS.
    - Si RAY_ADDRESS est défini, on s'y connecte (après avoir retiré d'éventuels guillemets).
    - Sinon, on tente 'auto' ; si ça échoue, on démarre un Ray *local*.
    La fonction est idempotente (ne relance pas Ray si déjà initialisé) et loggue l'adresse utilisée.
    """
    if ray.is_initialized():
        return
    raw = os.environ.get("RAY_ADDRESS", "").strip()
    address = raw.strip("'\"")  # nettoie d'éventuels guillemets
    try:
        if address:
            ray.init(address=address, ignore_reinit_error=True, logging_level="ERROR")
        else:
            try:
                ray.init(address="auto", ignore_reinit_error=True, logging_level="ERROR")
            except Exception:
                ray.init(ignore_reinit_error=True, logging_level="ERROR")
    except Exception:
        if not ray.is_initialized():
            ray.init(ignore_reinit_error=True, logging_level="ERROR")


# ---------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------
@dag(
    dag_id="train_model",
    schedule=None,  # déclenchement manuel (adapte si besoin)
    start_date=timezone.datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["prep", "reservations", "vehicles", "ray", "train"],
)
def data_prep_reservations_ray():
    """
    1) Prépare un dataset par véhicule avec total_reservations et sélection de variables
       corrélées à la cible, puis exporte dans /app/datas/datas.csv. Accélère l'agrégation
       des réservations avec Ray (utilise RAY_ADDRESS, ex: ray://ray:10001).
    2) Groupe de tâches *train_models* qui lance l'entraînement des modèles listés
       dans les variables d'env MODEL_NAMES / MODEL_PATHS (dans PROJECT_DIR),
       et propage la configuration de tracking (TRACKING_HOST/PORT).
    """

    # -------------------
    # Préparation des data
    # -------------------
    @task
    def check_inputs() -> dict:
        missing = [p for p in (INPUT_RESERVATIONS, INPUT_VEHICLES) if not os.path.exists(p)]
        if missing:
            raise FileNotFoundError(f"Fichier(s) introuvable(s): {missing}")
        out_dir = os.path.dirname(OUTPUT_DATASET)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        return {"reservations": INPUT_RESERVATIONS, "vehicles": INPUT_VEHICLES}

    @task
    def aggregate_reservations_with_ray(paths: dict) -> str:
        """
        Agrège le nombre de réservations par vehicle_id -> total_reservations avec **Ray Core (MapReduce)**
        pour éviter les problèmes connus de Ray **Client + Ray Data** (groupby/shuffle) en mode `ray://`.
        Si Ray n'est pas disponible, fallback automatique en pandas pur.
        """
        try:
            _ray_init()
            if not ray.is_initialized():
                raise RuntimeError("Ray non initialisé après _ray_init().")

            try:
                print(f"[Ray] version={ray.__version__} resources={ray.cluster_resources()}")
            except Exception:
                pass

            @ray.remote
            def map_counts(pdf: pd.DataFrame):
                s = pdf["vehicle_id"].value_counts(dropna=False)
                return s.astype("int64")

            futures = []
            for chunk in pd.read_csv(paths["reservations"], usecols=["vehicle_id"], chunksize=1_000_000):
                futures.append(map_counts.remote(chunk))

            if not futures:
                agg_df = pd.DataFrame({"vehicle_id": [], "total_reservations": []})
            else:
                counts = ray.get(futures)
                total = reduce(lambda a, b: a.add(b, fill_value=0), counts)
                total = total.astype("int64")
                agg_df = total.rename_axis("vehicle_id").reset_index(name="total_reservations")
        except Exception as e:
            print(f"[WARN] Ray indisponible ou échec MapReduce, fallback pandas. Raison: {e}")
            df = pd.read_csv(paths["reservations"], usecols=["vehicle_id"])
            agg_df = (
                df["vehicle_id"].value_counts(dropna=False)
                .rename_axis("vehicle_id").reset_index(name="total_reservations")
            )
        finally:
            try:
                if ray.is_initialized():
                    ray.shutdown()
            except Exception:
                pass

        agg_df = agg_df.dropna(subset=["vehicle_id"]).copy()
        agg_df.to_csv(TMP_AGG, index=False)
        return TMP_AGG

    @task
    def merge_with_vehicles(agg_path: str, paths: dict) -> str:
        """Jointure gauche des véhicules avec l'agrégat de réservations."""
        vehicles = pd.read_csv(paths["vehicles"])
        if "vehicle_id" not in vehicles.columns:
            raise KeyError("Colonne 'vehicle_id' absente de vehicles.csv")
        agg = pd.read_csv(agg_path)
        merged = vehicles.merge(agg, on="vehicle_id", how="left")
        merged["total_reservations"] = merged["total_reservations"].fillna(0)
        with np.errstate(invalid="ignore"):
            merged["total_reservations"] = merged["total_reservations"].astype(int)
        merged.to_csv(TMP_MERGED, index=False)
        return TMP_MERGED

    @task
    def select_significant_features(merged_path: str, threshold: float = 0.02) -> str:
        """
        - Corrélation (Pearson) avec 'total_reservations'
        - Sélection des variables |corr| > threshold (0.02 par défaut)
        - Renomme la cible en 'target' dans le dataset final -> /app/datas/datas.csv
        """
        merged = pd.read_csv(merged_path)
        if "total_reservations" not in merged.columns:
            raise KeyError("'total_reservations' manquant après la jointure.")
        num_df = merged.select_dtypes(include=[np.number]).copy()
        corr = num_df.corr(method="pearson")["total_reservations"].abs()
        selected = corr[corr > threshold].index.tolist()
        if "total_reservations" not in selected:
            selected.append("total_reservations")
        final_df = num_df[selected].copy()
        final_df = final_df.rename(columns={"total_reservations": "target"})
        final_df.to_csv(OUTPUT_DATASET, index=False)
        return OUTPUT_DATASET

    # -------------------
    # Groupe d'entraînement
    # -------------------
    @task_group(group_id="train_models")
    def train_models_group(dataset_path: str):
        """
        Crée un sous-ensemble de tâches dynamiques (une par modèle) à partir
        de MODEL_NAMES / MODEL_PATHS. Chaque tâche cherche un script de training :
          - PRIORITÉ:  <PROJECT_DIR>/<model_path>/train.py
          - SINON:     python -m <model_path>.train
        Les arguments suivants sont fournis si le script les supporte:
          --data, --tracking-uri, --run-name
        De plus, les variables d'env MLFLOW_TRACKING_URI et RUN_NAME sont exportées.
        """

        @task
        def build_specs(model_names: str, model_paths: str, project_dir: str) -> list[dict]:
            names = [n.strip() for n in model_names.split(",") if n.strip()]
            paths = [p.strip() for p in model_paths.split(",") if p.strip()]
            if len(names) != len(paths):
                raise ValueError(
                    "MODEL_NAMES et MODEL_PATHS doivent avoir la même longueur (ex: 'A,B' et 'a,b')."
                )
            specs: list[dict] = []
            for name, path in zip(names, paths):
                abs_dir = os.path.join(project_dir, path)
                specs.append({
                    "name": name,
                    "path": path,
                    "abs_dir": abs_dir,
                })
            return specs

        @task
        def train_one(spec: dict, dataset_path: str, tracking_host: str, tracking_port: str) -> str:
            # Déduit la commande à exécuter
            train_py = os.path.join(spec["abs_dir"], "train.py")

            # Prépare env (utile si le script utilise MLflow)
            env = os.environ.copy()
            env.update({
                "MLFLOW_TRACKING_URI": f"http://{tracking_host}:{tracking_port}",
                "RUN_NAME": spec["name"],
            })

            if os.path.exists(train_py):
                cmd = [
                    sys.executable,
                    train_py,
                    "--data", dataset_path,
                    "--tracking-uri", f"http://{tracking_host}:{tracking_port}",
                    "--run-name", spec["name"],
                ]
            else:
                # Essaye en module: python -m <path>.train
                module = f"{spec['path'].replace('/', '.').replace('-', '_')}.train"
                cmd = [
                    sys.executable,
                    "-m",
                    module,
                    "--data", dataset_path,
                    "--tracking-uri", f"http://{tracking_host}:{tracking_port}",
                    "--run-name", spec["name"],
                ]

            try:
                print(f"[TRAIN] {spec['name']} -> {' '.join(cmd)} (cwd={spec['abs_dir']})")
                completed = subprocess.run(
                    cmd,
                    cwd=spec["abs_dir"] if os.path.exists(spec["abs_dir"]) else None,
                    check=True,
                    text=True,
                    capture_output=True,
                    env=env,
                )
                # Log stdout pour debug dans Airflow
                if completed.stdout:
                    print(completed.stdout)
                if completed.stderr:
                    print(completed.stderr)
                return f"{spec['name']}: OK"
            except FileNotFoundError:
                # Aucun script trouvé dans le dossier -> skip propre
                raise AirflowSkipException(
                    f"Aucun script 'train.py' trouvé et module introuvable pour {spec['name']} dans {spec['abs_dir']}"
                )
            except subprocess.CalledProcessError as e:
                # Erreur d'exécution du script -> erreur de tâche
                stderr_preview = (e.stderr or "")[:1000]
                raise RuntimeError(
                    f"Echec d'entraînement {spec['name']} (code {e.returncode}).\n" + stderr_preview
                )

        specs = build_specs(MODEL_NAMES, MODEL_PATHS, PROJECT_DIR)
        # Mapping dynamique: une tâche par modèle
        train_one.partial(
            dataset_path=dataset_path,
            tracking_host=TRACKING_HOST,
            tracking_port=TRACKING_PORT,
        ).expand(spec=specs)

    # Chaînage global
    paths = check_inputs()
    agg = aggregate_reservations_with_ray(paths)
    merged = merge_with_vehicles(agg, paths)
    output = select_significant_features(merged)

    # Lance le groupe d'entraînement après la préparation du dataset
    train_models_group(output)


# Instance DAG
dag = data_prep_reservations_ray()
