import os, time, pytest, httpx

@pytest.fixture(scope="session")
def settings():
    ui = os.environ.get("AIRFLOW_UI_BASE_URL", "http://airflow_api-server:8080").rstrip("/")
    api_prefix = os.environ.get("AIRFLOW_API_PREFIX", "/api/v2")
    base_url = ui + api_prefix
    token = os.environ.get("AIRFLOW_BEARER_TOKEN")
    username = os.environ.get("AIRFLOW_USERNAME")
    password = os.environ.get("AIRFLOW_PASSWORD")
    dag_ids = [d.strip() for d in os.environ.get("DAG_IDS","").split(",") if d.strip()]
    timeout = int(os.environ.get("ITEST_TIMEOUT","10"))
    poll = int(os.environ.get("ITEST_POLL_EVERY","5"))
    assert dag_ids, "Aucun DAG fourni (env DAG_IDS)"
    return {
        "ui": ui, "base_url": base_url, "api_prefix": api_prefix,
        "token": token, "username": username, "password": password,
        "dag_ids": dag_ids, "timeout": timeout, "poll": poll
    }

def _get_token(ui_base, username, password):
    # Airflow 3 (Auth Manager) -> POST /auth/token
    r = httpx.post(
        f"{ui_base}/auth/token",
        json={"username": username, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]

@pytest.fixture(scope="session")
def client(settings):
    token = settings["token"]
    if not token and settings["username"] and settings["password"]:
        token = _get_token(settings["ui"], settings["username"], settings["password"])
    assert token, "Pas de token. Fournis AIRFLOW_BEARER_TOKEN ou (AIRFLOW_USERNAME+AIRFLOW_PASSWORD)."

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=settings["base_url"], headers=headers, timeout=10) as c:
        yield c

# Attendre que l’API soit up
@pytest.fixture(scope="session", autouse=True)
def wait_api_ready(settings):
    deadline = time.time() + 10
    last = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{settings['ui']}/monitor/health", timeout=10)
            if r.status_code == 200:
                return
        except Exception as e:
            last = e
        time.sleep(2)
    pytest.fail(f"API non prête: {last}")

def pytest_generate_tests(metafunc):
    if "dag_id" in metafunc.fixturenames:
        dag_ids = [d.strip() for d in os.environ.get("DAG_IDS","").split(",") if d.strip()]
        metafunc.parametrize("dag_id", dag_ids)
