# Test container only (keeps runtime image clean)
FROM python:3.8-slim

# ---- Default env (override in compose/CI) ----
# MLflow tracking reste accessible sur le service 'mlflow'
ENV MLFLOW_TRACKING_URI=http://mlflow:5000
# On cible le proxy HTTP Serve qui vit sur le service 'ray'
ENV RAY_HTTP_HOST=ray
ENV RAY_HTTP_PORT=8000
ENV EXPERIMENT_NAMES="XGBoost0, XGBoost1, XGBoost2"
ENV WAIT_TIMEOUT=60
# Ne pas définir MODEL_URLS: la fixture les construit automatiquement
# (si tu préfères, tu peux les définir explicitement ici)

WORKDIR /tests

COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt

# Copy test suite
COPY tests/ /tests/

CMD ["pytest", "-q",  "--disable-warnings"]
