# CI/CD Pipeline Overview

This repository ships with a self-hosted GitHub Actions workflow defined in [`mlflow-ci-cd.yml`](./mlflow-ci-cd.yml). The workflow orchestrates the lifecycle of the platform's service containers to validate changes end-to-end every time code is pushed to `master` or a pull request is updated.

## Workflow structure

The pipeline is composed of the following jobs executed in order:

1. **`clear-containers`** &mdash; stops and removes any containers created by previous runs for every service declared in the main `docker-compose.yml` file. It also reads the semantic version from [`.version`](../.version) so that downstream jobs can reuse the tag.
2. **`clear-network`** &mdash; removes the branch-specific Docker network, ensuring a clean environment before the build.
3. **`create-network`** &mdash; recreates the isolated Docker network that will be shared by the rebuilt containers.
4. **`build`** &mdash; builds fresh images for each service (Airflow components, MLflow, Ray, observability stack, etc.) using Docker Buildx and tags them with the `<branch>-<version>` convention.
5. **`start-containers`** &mdash; runs the long-lived services on the shared network, wiring environment variables, volumes, capabilities, and exposed ports exactly as defined in `docker-compose.yml`.
6. **`test-containers`** &mdash; launches the dedicated test containers from [`docker-compose.test.yml`](../../docker-compose.test.yml) to execute the integration test suite against the running services.
7. **`prune-unused-images`** &mdash; reclaims disk space on the self-hosted runner by removing dangling images.
8. **`stop-containers`** &mdash; stops every container started earlier in the run so the self-hosted runner returns to an idle state.
9. **`remove-network`** &mdash; tears down the branch-specific Docker network if it still exists.

> **Tip:** Each job calculates the branch-aware image tag and network name in the same way (by replacing `/` with `-`), so inspecting the workflow logs can help you trace the exact resources created for a run.

## Integration tests

Integration coverage is provided by the services defined in [`docker-compose.test.yml`](../../docker-compose.test.yml):

- **`mlflow_test`**: builds the image in [`mlflow_test/`](../../mlflow_test/) and executes `pytest` inside the container. The tests validate that the MLflow tracking server is reachable at `http://mlflow:5000`, that the expected set of experiments (`XGBoost`, `SVR`, `CatBoost`, `KNN`) can be registered, and that the overall workflow completes within the configured timeout.
- **`airflow_test`**: builds the image in [`airflow_test/`](../../airflow_test/) and drives the Airflow REST API to confirm the target DAGs (`example_dag` and `ray_integration`) can be triggered and finish successfully. Credentials, polling frequency, and timeouts are injected through environment variables to mimic production usage.

Running the test suite locally follows the same pattern as the CI workflow:

```bash
# Recreate the test network if necessary
export BRANCH_NAME="$(git branch --show-current | tr '/' '-')"
export VERSION="$(cat .version)"
docker network create "network-${BRANCH_NAME}" || true

# Build the service images used by the tests
for service in mlflow mlflow_test postgres redis airflow_init airflow_api-server \
               airflow_scheduler airflow_triggerer airflow_dag-processor \
               airflow_worker ray statsd-exporter prometheus grafana; do
  (cd "$service" && docker build -t "$service:${BRANCH_NAME}-${VERSION}" .)
done

# Start the runtime dependencies
for service in mlflow postgres redis airflow_init airflow_api-server airflow_scheduler \
               airflow_triggerer airflow_dag-processor airflow_worker ray \
               statsd-exporter prometheus grafana; do
  docker run -d --name "$service-${BRANCH_NAME}" --network "network-${BRANCH_NAME}" \
    "$service:${BRANCH_NAME}-${VERSION}"
done

# Launch the integration test containers
for test_service in mlflow_test airflow_test; do
  docker run --rm --name "$test_service-${BRANCH_NAME}" --network "network-${BRANCH_NAME}" \
    "$test_service:${BRANCH_NAME}-${VERSION}"
done

# Clean up
for service in mlflow mlflow_test postgres redis airflow_init airflow_api-server \
               airflow_scheduler airflow_triggerer airflow_dag-processor \
               airflow_worker airflow_test ray statsd-exporter prometheus grafana; do
  docker rm -f "$service-${BRANCH_NAME}" || true
done
docker network rm "network-${BRANCH_NAME}" || true
```

Feel free to tweak the list of services if you only need a subset for local validation. The key idea is to reproduce the network, build, and run phases exactly as the workflow does so that integration tests interact with the same container topology the CI/CD pipeline manages automatically.
