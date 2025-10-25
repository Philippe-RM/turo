import pytest

def _list_all_dag_ids(client, limit=100):
    """Return the full set of DAG IDs (active + paused) with pagination."""
    dag_ids = set()
    offset = 0
    while True:
        r = client.get("/dags", params={"only_active": "false", "limit": limit, "offset": offset}, timeout=30)
        assert r.status_code == 200, f"GET /dags failed: {r.status_code}\nBody: {r.text[:500]}"
        data = r.json()
        items = data.get("dags", [])
        for d in items:
            dag_ids.add(d.get("dag_id"))
        total = data.get("total_entries", len(items))
        offset += limit
        if offset >= total or not items:
            break
    return dag_ids

def test_dags_are_listed(client, settings):
    present = _list_all_dag_ids(client)
    # Optional: print a short sample for visibility
    print(f"[itest] DAGs present ({len(present)}): {sorted(list(present))[:20]}{' ...' if len(present) > 20 else ''}")

    missing = [d for d in settings["dag_ids"] if d not in present]
    assert not missing, (
        "Missing DAGs: "
        f"{missing}. Present ({len(present)}): {sorted(present)}"
    )
