import os
import pytest
import requests

@pytest.mark.skipif(
    not os.getenv("MODEL_URLS"),
    reason="MODEL_URLS not set; skipping serving tests."
)
def test_ping(model_urls):
    """Model server should respond to /ping with 200."""
    for url in model_urls:
        r = requests.get(f"{url}/ping", timeout=5)
        assert r.status_code == 200

@pytest.mark.skipif(
    not os.getenv("MODEL_URLS"),
    reason="MODEL_URLS not set; skipping serving tests."
)
def test_invocations_basic_contract(model_urls):
    """
    /invocations should not 5xx on bad input.
    We expect 200 if payload matches your model schema,
    or a 4xx (e.g. 400/415/422) otherwise — but never 5xx.
    """
    bad_payload = {"not": "your_schema"}
    for url in model_urls:
        r = requests.post(f"{url}/invocations", json=bad_payload, timeout=5)
        assert r.status_code < 500
