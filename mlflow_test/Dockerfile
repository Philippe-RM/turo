# Test container only (keeps runtime image clean)
FROM python:3.8-slim

# ---- Default env (override in compose/CI) ----

ENV MLFLOW_TRACKING_URI ${MLFLOW_TRACKING_URI:-"http://mlflow:5000"}
ENV EXPERIMENT_NAME ${EXPERIMENT_NAME:-"XGBoost_Experiment"}
ENV MODEL_URL ${MODEL_URL:-"http://mlflow:5001"}
ENV WAIT_TIMEOUT ${WAIT_TIMEOUT:-"60" }


WORKDIR /tests
COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt

# Copy test suite
COPY tests/ /tests/

# Default command (can be overridden)
CMD ["pytest", "-q", "--maxfail=1", "--disable-warnings"]
