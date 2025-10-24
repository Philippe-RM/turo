# All comments in English.
import requests
import mlflow
from mlflow.tracking import MlflowClient

def test_tracking_ui_http_ok(tracking_uri):
    """UI/HTTP endpoint should be reachable (status < 400)."""
    r = requests.get(tracking_uri, allow_redirects=True, timeout=5)
    assert r.status_code < 400

def test_experiment_exists(experiment_name):
    """Expected experiment should exist (created by entrypoint or manually)."""
    client = MlflowClient()
    exp = client.get_experiment_by_name(experiment_name)
    assert exp is not None, f"Experiment '{experiment_name}' not found"
