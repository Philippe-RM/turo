from __future__ import annotations

import os
import pandas as pd
import numpy as np

from airflow.decorators import dag, task
from airflow.utils import timezone

import ray

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
    # Nettoyage d'éventuels guillemets YAML "ray://..." -> ray://...
    address = raw.strip("'\"")
    try:
        if address:
            ray.init(address=address, ignore_reinit_error=True, logging_level="ERROR")
        else:
            # essaie 'auto' d'abord
            try:
                ray.init(address="auto", ignore_reinit_error=True, logging_level="ERROR")
            except Exception:
                # fallback: cluster local
                ray.init(ignore_reinit_error=True, logging_level="ERROR")
    except Exception:
        # dernier filet de sécurité: cluster local
        if not ray.is_initialized():
            ray.init(ignore_reinit_error=True, logging_level="ERROR")


@dag(
    dag_id="prepare_data",
    schedule=None,  # déclenchement manuel (adapte si besoin)
    start_date=timezone.datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["prep", "reservations", "vehicles", "ray"],
)
def data_prep_reservations_ray():
    """
    Prépare un dataset par véhicule avec total_reservations et sélection de variables
    corrélées à la cible, puis exporte dans /app/datas/datas.csv. Accélère l'agrégation
    des réservations avec Ray (utilise RAY_ADDRESS, ex: ray://ray:10001).
    """

    @task
    def check_inputs():
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
        Agrège le nombre de réservations par vehicle_id -> total_reservations en s'appuyant sur **Ray Core (MapReduce)**
        pour éviter les problèmes connus de Ray **Client + Ray Data** (groupby/shuffle) en mode `ray://`.
        Si Ray n'est pas disponible, fallback automatique en pandas pur.
        """
        try:
            _ray_init()
            if not ray.is_initialized():
                raise RuntimeError("Ray non initialisé après _ray_init().")

            # Log de contrôle: versions & ressources (utile dans les logs Airflow)
            try:
                print(f"[Ray] version={ray.__version__} resources={ray.cluster_resources()}")
            except Exception:
                pass

            # --- MAP (exécuté sur le cluster) : value_counts par chunk ---
            @ray.remote
            def map_counts(pdf):
                s = pdf["vehicle_id"].value_counts(dropna=False)
                # S'assurer d'un type stable pour l'agrégation
                return s.astype("int64")

            # Lecture en chunks côté driver
            futures = []
            for chunk in pd.read_csv(
                paths["reservations"], usecols=["vehicle_id"], chunksize=1_000_000
            ):
                futures.append(map_counts.remote(chunk))

            if not futures:
                agg_df = pd.DataFrame({"vehicle_id": [], "total_reservations": []})
            else:
                counts = ray.get(futures)
                # --- REDUCE : somme élément par élément des Series ---
                from functools import reduce
                import pandas as _pd
                total = reduce(lambda a, b: a.add(b, fill_value=0), counts)
                total = total.astype("int64")
                agg_df = total.rename_axis("vehicle_id").reset_index(name="total_reservations")

        except Exception as e:
            # Fallback : agrégation pandas côté driver
            print(f"[WARN] Ray indisponible ou échec MapReduce, fallback pandas. Raison: {e}")
            df = pd.read_csv(paths["reservations"], usecols=["vehicle_id"])
            agg_df = (
                df["vehicle_id"].value_counts(dropna=False)
                .rename_axis("vehicle_id").reset_index(name="total_reservations")
            )
        finally:
            # Ferme proprement la session Ray si ouverte
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
        """
        Jointure gauche des véhicules avec l'agrégat de réservations.
        (On reste en pandas pour conserver la sémantique 'left' strictement identique.)
        """
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
        Reproduit la logique d'origine:
        - Corrélation (Pearson) avec 'total_reservations'
        - Sélection des variables |corr| > threshold (0.02 par défaut)
        - Renomme la cible en 'target' dans le dataset final
        - Sauvegarde finale -> /app/datas/datas.csv
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
        # Renommer la cible dans le fichier de sortie
        final_df = final_df.rename(columns={"total_reservations": "target"})
        final_df.to_csv(OUTPUT_DATASET, index=False)
        return OUTPUT_DATASET

    paths = check_inputs()
    agg = aggregate_reservations_with_ray(paths)
    merged = merge_with_vehicles(agg, paths)
    output = select_significant_features(merged)

    output  # dépendance terminale


dag = data_prep_reservations_ray()
