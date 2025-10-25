# All comments in English.
import requests
import mlflow
from mlflow.tracking import MlflowClient

def test_tracking_ui_http_ok(tracking_uri):
    """UI/HTTP endpoint should be reachable (status < 400)."""
    r = requests.get(tracking_uri, allow_redirects=True, timeout=5)
    assert r.status_code < 400

def test_experiments_exist(experiment_names):
    """Expected experiments should exist (created by entrypoint or manually)."""
    client = MlflowClient()
    for name in experiment_names:
        exp = client.get_experiment_by_name(name)
        assert exp is not None, f"Experiment '{name}' not found"
