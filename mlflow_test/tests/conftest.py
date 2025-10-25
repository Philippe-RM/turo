# All comments in English.
import os
import time
import requests
import pytest
import mlflow
from mlflow.tracking import MlflowClient

def _wait_http_ready(url: str, timeout: int = 60):
    """Poll an HTTP endpoint until it returns < 400 or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, allow_redirects=True, timeout=5)
            if r.status_code < 400:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"Service not ready at {url}")

@pytest.fixture(scope="session")
def tracking_uri() -> str:
    return os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

@pytest.fixture(scope="session", autouse=True)
def tracking_ready(tracking_uri):
    """Ensure MLflow tracking server is reachable and client works."""
    _wait_http_ready(tracking_uri, timeout=int(os.getenv("WAIT_TIMEOUT", "60")))
    mlflow.set_tracking_uri(tracking_uri)
    MlflowClient().search_experiments()

@pytest.fixture(scope="session")
def experiment_names() -> list:
    names = os.getenv("EXPERIMENT_NAMES", "XGBoost0, XGBoost1, XGBoost2")
    return [name.strip() for name in names.split(",") if name.strip()]

@pytest.fixture(scope="session")
def model_urls(experiment_names) -> list:
    """
    Build Ray Serve URLs as:
      http://<RAY_HTTP_HOST>:<RAY_HTTP_PORT>/<model_name>
    Can be overridden by MODEL_URLS env (comma-separated).
    """
    env_urls = os.getenv("MODEL_URLS")
    if env_urls:
        return [u.strip() for u in env_urls.split(",") if u.strip()]

    host = os.getenv("RAY_HTTP_HOST", "ray")
    port = os.getenv("RAY_HTTP_PORT", "8000")
    base = f"http://{host}:{port}"
    return [f"{base}/{name}" for name in experiment_names]

@pytest.fixture(scope="session", autouse=True)
def serve_ready(model_urls):
    """Wait for each Ray Serve endpoint to be up ('ok' on GET)."""
    timeout = int(os.getenv("WAIT_TIMEOUT", "60"))
    for url in model_urls:
        _wait_http_ready(url, timeout=timeout)

@pytest.fixture(scope="session")
def model_url(model_urls):
    """Provide the first model URL by default for backward compatibility."""
    return model_urls[0] if model_urls else None
