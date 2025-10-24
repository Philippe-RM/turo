# Test container only (keeps runtime image clean)
FROM python:3.8-slim

# ---- Default env (override in compose/CI) ----
ENV MLFLOW_TRACKING_URI="http://mlflow:5000" \
    EXPERIMENT_NAME="XGBoost_Experiment" \
    MODEL_URL="" \
    WAIT_TIMEOUT="60"

WORKDIR /tests
COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt

# Copy test suite
COPY tests/ /tests/

# Default command (can be overridden)
CMD ["pytest", "-q", "--maxfail=1", "--disable-warnings"]
