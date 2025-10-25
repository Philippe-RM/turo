import json
import pytest

def test_api_health(client, settings):
    # v2 health endpoint lives under /api/v2/monitor/health
    url = "/monitor/health"
    r = client.get(url, timeout=30)

    # Helpful debug on failure
    assert r.status_code == 200, f"GET {settings['base_url']}{url} -> {r.status_code}\nBody: {r.text[:500]}"

    try:
        h = r.json()
    except Exception:
        pytest.fail(f"Non-JSON response from {settings['base_url']}{url}:\n{r.text[:500]}")

    print("\n[health] url:", settings["base_url"] + url)
    print("[health] body:\n", json.dumps(h, indent=2), "\n")

    assert h.get("metadatabase", {}).get("status") == "healthy", h
    assert h.get("scheduler", {}).get("status") == "healthy", h
