import time
import uuid
import json
from datetime import datetime, timezone
import pytest

TERMINAL_SUCCESS = {"success"}
TERMINAL_FAILURE = {"failed", "manual_failure"}

def _trigger_dag_run(client, dag_id: str, run_id: str):
    """Trigger a DAG run (v2 API requires logical_date)."""
    logical_date = datetime.now(timezone.utc).isoformat()
    payload = {
        "dag_run_id": run_id,
        "logical_date": logical_date,   # required by /api/v2
        "conf": {},
        # "note": "integration test",   # optional
    }
    r = client.post(f"/dags/{dag_id}/dagRuns", json=payload, timeout=30)
    assert r.status_code in (200, 201), (
        f"POST /dags/{dag_id}/dagRuns -> {r.status_code}\n"
        f"Req: {json.dumps(payload)}\n"
        f"Body: {r.text[:800]}"
    )
    data = r.json()
    returned = (data.get("dag_run_id") or "").strip()
    assert returned, f"Unexpected response body: {json.dumps(data, indent=2)[:800]}"
    print(f"[itest] Triggered {dag_id} with run_id={returned}")
    return returned

def _get_run_state(client, dag_id: str, run_id: str) -> str:
    r = client.get(f"/dags/{dag_id}/dagRuns/{run_id}", timeout=30)
    assert r.status_code == 200, (
        f"GET /dags/{dag_id}/dagRuns/{run_id} -> {r.status_code}\nBody: {r.text[:800]}"
    )
    data = r.json()
    return (data.get("state") or "").lower()

def _print_task_summary(client, dag_id: str, run_id: str):
    """Best-effort task instance summary for debugging."""
    tr = client.get(f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances", timeout=30)
    if tr.status_code != 200:
        print(f"[itest] Could not fetch taskInstances: HTTP {tr.status_code} – {tr.text[:800]}")
        return
    items = tr.json().get("task_instances", [])
    counts = {}
    for ti in items:
        s = (ti.get("state") or "").lower()
        counts[s] = counts.get(s, 0) + 1
    print(f"[itest] taskInstances by state: {counts}")
    for ti in items[:10]:
        print(f"[itest]  - {ti.get('task_id')} : {ti.get('state')}")

def _wait_for_success(client, dag_id: str, run_id: str, timeout: int, poll: int) -> bool:
    deadline = time.time() + timeout
    last_state = None
    while True:
        state = _get_run_state(client, dag_id, run_id)
        if state != last_state:
            print(f"[itest] {dag_id} run {run_id} -> state: {state.upper()}")
            last_state = state
        if state in TERMINAL_SUCCESS:
            return True
        if state in TERMINAL_FAILURE:
            _print_task_summary(client, dag_id, run_id)
            return False
        if time.time() > deadline:
            print(f"[itest] TIMEOUT after {timeout}s waiting for SUCCESS.")
            _print_task_summary(client, dag_id, run_id)
            return False
        time.sleep(poll)

def test_trigger_and_reach_success(client, settings, dag_id):
    # Give integrations enough time
    assert settings["timeout"] >= 30, f"Timeout too small: {settings['timeout']}s"

    run_id = f"itest-{uuid.uuid4().hex[:10]}"
    run_id = _trigger_dag_run(client, dag_id, run_id)

    ok = _wait_for_success(client, dag_id, run_id, settings["timeout"], settings["poll"])
    assert ok, f"{dag_id}: run {run_id} did not reach SUCCESS within {settings['timeout']}s"
