import os
import pytest
import requests

@pytest.mark.skipif(
    not os.getenv("EXPERIMENT_NAMES") and not os.getenv("MODEL_URLS"),
    reason="No model endpoints configured; skipping serving tests."
)
def test_ping(model_urls):
    """Ray Serve: GET on the route prefix should return 200 ('ok')."""
    for url in model_urls:
        r = requests.get(url, timeout=5)
        assert r.status_code == 200
        assert r.text.strip().lower() == "ok"

@pytest.mark.skipif(
    not os.getenv("EXPERIMENT_NAMES") and not os.getenv("MODEL_URLS"),
    reason="No model endpoints configured; skipping serving tests."
)
def test_invocations_basic_contract(model_urls):
    """
    Pour un payload invalide, le service est censé renvoyer 500 d'après le contrat choisi.
    """
    bad_payload = {"not": "your_schema"}
    for url in model_urls:
        r = requests.post(url, json=bad_payload, timeout=5)
        assert r.status_code == 500
