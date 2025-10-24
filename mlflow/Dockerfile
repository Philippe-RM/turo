# Use an official Python runtime as a parent image
FROM python:3.8-slim

# -------- Default environment variables (override in docker-compose) --------
ENV GIT_PYTHON_REFRESH ${GIT_PYTHON_REFRESH:-"quiet"}
ENV EXPERIMENT_NAME ${EXPERIMENT_NAME:-"XGBoost_Experiment"}
# Matches Dockerfile default
ENV PROJECT_DIR ${PROJECT_DIR:-"/app/projects/XGBoost"}   
ENV TRACKING_HOST ${TRACKING_HOST:-"127.0.0.1"}
ENV TRACKING_PORT ${TRACKING_PORT:-"5000"}
ENV MODEL_PORT ${MODEL_PORT:-"5001"}

# Backend & artifacts (mount these as persistent volumes in docker-compose)
ENV BACKEND_URI ${BACKEND_URI:-"sqlite:////mlflow/mlflow.db"}
ENV ARTIFACT_ROOT ${ARTIFACT_ROOT:-"/mlflow/artifacts"}

# Logging configuration (overridable)
# Directory where log files are written
ENV LOG_DIR ${LOG_DIR:-"/mlflow/logs"}                    
# debug|info|warning|error|critical
ENV GUNICORN_LOG_LEVEL ${GUNICORN_LOG_LEVEL:-"info"}      
ENV ACCESS_LOG_FILE ${ACCESS_LOG_FILE:-"$LOG_DIR/mlflow_access.log"}
ENV ERROR_LOG_FILE ${ERROR_LOG_FILE:-"$LOG_DIR/mlflow_error.log"}

# Set the working directory
WORKDIR /app

# Copy project sources (MLflow projects)
COPY projects /app/projects

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

# Tools needed by entrypoint and environment
RUN apt-get update && apt-get install -y --no-install-recommends jq bash \
    && rm -rf /var/lib/apt/lists/*

# Create persistent folders for MLflow backend and logs
RUN mkdir -p /mlflow/artifacts /mlflow/logs

# Expose MLflow tracking UI and model serving ports
EXPOSE 5000 5001

# Copy entrypoint and make it executable
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Persist DB, artifacts and logs across container restarts (optional but recommended)
VOLUME ["/mlflow"]

# Run entrypoint when the container launches
ENTRYPOINT ["/app/entrypoint.sh"]
