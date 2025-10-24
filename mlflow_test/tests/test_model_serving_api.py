# All comments in English.
import os
import pytest
import requests

pytestmark = pytest.mark.skipif(
    not os.getenv("MODEL_URL"),
    reason="MODEL_URL not set; skipping serving tests."
)

def test_ping(model_url):
    """Model server should respond to /ping with 200."""
    r = requests.get(f"{model_url}/ping", timeout=5)
    assert r.status_code == 200

def test_invocations_basic_contract(model_url):
    """
    /invocations should not 5xx on bad input.
    We expect 200 if payload matches your model schema,
    or a 4xx (e.g. 400/415/422) otherwise — but never 5xx.
    """
    bad_payload = {"not": "your_schema"}
    r = requests.post(f"{model_url}/invocations", json=bad_payload, timeout=5)
    assert r.status_code < 500
