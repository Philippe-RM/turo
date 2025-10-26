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
from airflow.utils.trigger_rule import TriggerRule

# ---------------------------------------------------------------------
# ENV / Paramètres
# ---------------------------------------------------------------------
PROJECT_DIR = os.getenv("PROJECT_DIR", "/app/projects")
TRACKING_HOST = os.getenv("TRACKING_HOST", "127.0.0.1")
TRACKING_PORT = os.getenv("TRACKING_PORT", "5000")
MODEL_NAMES = os.getenv("MODEL_NAMES", "XGBoost0, XGBoost1, XGBoost2")
MODEL_PATHS = os.getenv("MODEL_PATHS", "XGBoost0, XGBoost1, XGBoost2")
# Stage optionnel de registry (ex: "Staging", "Production")
REGISTER_STAGE = os.getenv("REGISTER_STAGE", "")
# Patience maximum (secondes) pour attendre FINISHED + apparition des artefacts
REGISTER_WAIT_SECS = int(os.getenv("REGISTER_WAIT_SECS", "120"))
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
    """
    if ray.is_initialized():
        return
    raw = os.environ.get("RAY_ADDRESS", "").strip()
    address = raw.strip("'\"")
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
    dag_id="prepare_data",
    schedule=None,
    start_date=timezone.datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["prep", "reservations", "vehicles", "ray", "train", "register"],
)
def data_prep_reservations_ray():
    """
    1) Prépare les données -> /app/datas/datas.csv
    2) Entraîne chaque modèle (exp MLflow = MODEL_NAME, artifact unique)
    3) Enregistre une nouvelle version en registry après attente FINISHED + artefact présent
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
        """Agrège le nombre de réservations par vehicle_id avec Ray Core (fallback pandas)."""
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
        - Sélection des variables |corr| > threshold
        - Renomme 'total_reservations' -> 'target'
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
    # Spécifications (artifact aléatoire par modèle)
    # -------------------
    @task
    def build_specs(model_names: str, model_paths: str, project_dir: str) -> list[dict]:
        names = [n.strip() for n in model_names.split(",") if n.strip()]
        paths = [p.strip() for p in model_paths.split(",") if p.strip()]
        if len(names) != len(paths):
            raise ValueError("MODEL_NAMES et MODEL_PATHS doivent avoir la même longueur (ex: 'A,B' et 'a,b').")
        specs: list[dict] = []
        for name, path in zip(names, paths):
            abs_dir = os.path.join(project_dir, path)
            specs.append({"name": name, "path": path, "abs_dir": abs_dir})
        return specs

    # -------------------
    # Groupe d'entraînement
    # -------------------
    @task_group(group_id="train_models")
    def train_models_group(dataset_path: str, specs: list[dict]):
        """
        - Fixe l'expérience MLflow = MODEL_NAME
        """
        @task
        def train_one(spec: dict, dataset_path: str, tracking_host: str, tracking_port: str) -> str:
            import os
            import sys
            import subprocess
            import mlflow

            # Configure MLflow tracking URI
            tracking_uri = f"http://{tracking_host}:{tracking_port}"
            mlflow.set_tracking_uri(tracking_uri)

            # Get experiment ID from experiment name
            experiment_name = spec["name"]
            experiment = mlflow.get_experiment_by_name(experiment_name)
            if experiment is None:
                # If experiment does not exist, create it
                experiment_id = mlflow.create_experiment(experiment_name)
            else:
                experiment_id = experiment.experiment_id


            os.environ["MLFLOW_TRACKING_URI"] = tracking_uri
            # Prepare the command
            full_model_path = f"{os.environ.get("PROJECT_DIR")}/{spec["path"]}"  # Assurez-vous que cela pointe vers le bon chemin
            run_name = f"{spec['name']}_run"
            cmd = [
                sys.executable, "-m", "mlflow", "run", full_model_path,
                "--experiment-id", str(experiment_id),
                "--env-manager", "local",
                "--run-name", run_name,
            ]

            # Print debug information
            print("[DEBUG] ==== TRAIN CONTEXT ====")
            print(f"model_name={spec['name']}")
            print(f"project_dir={spec['abs_dir']}")
            print(f"dataset_path={dataset_path} exists={os.path.exists(dataset_path)} "
                f"size={os.path.getsize(dataset_path) if os.path.exists(dataset_path) else 'NA'}")
            print(f"MLFLOW_TRACKING_URI={tracking_uri}")
            print(f"MLFLOW_EXPERIMENT_ID={experiment_id}")
            print(f"[TRAIN] {spec['name']} -> {' '.join(cmd)} (cwd={spec['abs_dir']})")
            print(f"[TRAIN]  cmd {cmd}")
             # Execute the command
            completed = subprocess.run(
                cmd,
                cwd=spec["abs_dir"] if os.path.exists(spec["abs_dir"]) else None,
                check=True,
                text=True,
                capture_output=True,
            )
            print(f"[TRAIN]  {completed}")
            if completed.stdout:
                print("[TRAIN STDOUT]\n" + completed.stdout)
            if completed.stderr:
                print("[TRAIN STDERR]\n" + completed.stderr)
            return f"{spec['name']}: OK"

        # Mapping dynamique
        train_tasks = train_one.partial(
            dataset_path=dataset_path,
            tracking_host=TRACKING_HOST,
            tracking_port=TRACKING_PORT,
        ).expand(spec=specs)
        return train_tasks

    # -------------------
    # Groupe d'enregistrement (Model Registry MLflow)
    # -------------------
    @task_group(group_id="register_models")
    def register_models_group(specs: list[dict]):
        """
        Attend FINISHED et trouve un dossier d'artifact contenant `MLmodel` :
        - priorité à `spec['artifact_name']` s'il existe en racine,
        - sinon exploration récursive (ex: `models/m-.../artifacts`).
        """
        @task(trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)
        def register_one(spec: dict, tracking_host: str, tracking_port: str, stage: str, wait_secs: int) -> str:
            import time
            import posixpath
            import mlflow
            from mlflow.tracking import MlflowClient
            tracking_uri = f"http://{tracking_host}:{tracking_port}"
            mlflow.set_tracking_uri(tracking_uri)
            client = MlflowClient(tracking_uri=tracking_uri)
            exp = client.get_experiment_by_name(spec["name"])
            if not exp:
                raise AirflowSkipException(f"Aucune expérience MLflow nommée '{spec['name']}' — entraine d'abord le modèle.")
            exp_ids = [exp.experiment_id]
            # Dernier run FINISHED (tags prioritaires)
            queries = [
                f"tags.mlflow.runName = '{spec['name']}' and attributes.status = 'FINISHED'",
                f"tags.model_name = '{spec['name']}' and attributes.status = 'FINISHED'",
                "attributes.status = 'FINISHED'",
            ]
            df = None
            for q in queries:
                df = mlflow.search_runs(
                    experiment_ids=exp_ids,
                    filter_string=q,
                    order_by=["start_time DESC"],
                    max_results=1,
                )
                if df is not None and len(df.index) > 0:
                    print(f"[REGISTER] filtre match: {q}")
                    break
            if df is None or len(df.index) == 0:
                raise AirflowSkipException(f"Aucun run FINISHED trouvé dans l'expérience '{spec['name']}'")
            row = df.iloc[0]
            run_id = row.get("run_id") or row.get("run.info.run_id")
            print(f"[REGISTER] run_id={run_id} (exp={exp.experiment_id})")


            # Attente active : FINISHED + artefact exploitable
            deadline = time.time() + max(5, wait_secs)
            poll = 2
            chosen_artifact = None
            artifact_uri = None
            while True:
                r = client.get_run(run_id)
                print(f"[DEBUG] Objet Run: {r}")  # Log de debug pour voir l'objet Run
                print(f"[DEBUG] Type de l'objet Run: {type(r)}")  # Log de debug pour voir le type de l'objet Run
                print(f"[DEBUG] Attributs de l'objet Run: {dir(r)}")  # Log de debug pour voir les attributs de l'objet Run
                
                if hasattr(r, 'info') and hasattr(r.info, 'status'):
                    status = r.info.status
                    print(f"[DEBUG] Status trouvé via r.info.status: {status}")  # Log de debug pour voir le status
                # Accès sécurisé aux attributs de l'objet Run
                status = None
                if hasattr(r, 'info') and hasattr(r.info, 'status'):
                    status = r.info.status
                    print(f"[DEBUG] r.info {r.info}")
                    print(f"[DEBUG] r.outputs {r.outputs}")
                    model_id = r.outputs.model_outputs[0].model_id
                    run_id=r.info.run_id
                    print(f"[DEBUG] model_id {model_id}")
                    local_path = f"/mlflow/artifacts/{spec['name']}/models/{model_id}"
                    print(f"local_path  {local_path}")

                    print(f"Le modèle a été téléchargé à : {local_path}")
                    if status == "FINISHED":
                        status = r.info.status
                        artifact_uri = r.info.artifact_uri
                        break
                time.sleep(poll)
            
            print(f" local_path {local_path}")
            if not local_path:
                raise RuntimeError("Aucun dossier d'artifact contenant 'MLmodel' n'a été trouvé pour ce run.")


            model_uri = f"runs:/{run_id}/model"
            print(f" model_uri {model_uri}")
            mv = mlflow.register_model(model_uri=model_uri, name=spec["name"])

        register_tasks = register_one.partial(
            tracking_host=TRACKING_HOST,
            tracking_port=TRACKING_PORT,
            stage=REGISTER_STAGE,
            wait_secs=REGISTER_WAIT_SECS,
        ).expand(spec=specs)
        return register_tasks

    # Chaînage global
    paths = check_inputs()
    agg = aggregate_reservations_with_ray(paths)
    merged = merge_with_vehicles(agg, paths)
    output = select_significant_features(merged)
    # Spécs communes (incluent un artifact unique par modèle)
    specs = build_specs(MODEL_NAMES, MODEL_PATHS, PROJECT_DIR)
    # 1) Entraînement
    train_models = train_models_group(output, specs)
    # 2) Enregistrement en registry après entraînement
    mlflow_models = register_models_group(specs)
    train_models >> mlflow_models

# Instance DAG
dag = data_prep_reservations_ray()
