# JupyterLab workspace

The `jupyter` service provides a ready-to-use JupyterLab instance for exploring data, testing MLflow models, or calling Ray Serve endpoints.

## Usage

- The container exposes port `8888`.  After running `docker compose up -d`, inspect the container logs to retrieve the access token:
  ```bash
  docker compose logs -f jupyter
  ```
- Open the URL shown in the logs (`http://127.0.0.1:8888/lab?...`).
- Work notebooks are stored under the `notebooks/` folder in this repository and are mounted at `/notebooks` inside the container.

## Preinstalled libraries

Dependencies listed in [`requirements.txt`](./requirements.txt) are installed during the image build.  They include pandas, scikit-learn, MLflow, Ray, and visualisation packages commonly used when analysing the demo datasets.  Modify the file and rebuild the service if you need extra libraries:

```bash
docker compose build jupyter
```

## Shared data

The service mounts:

- `../datas` → `/data`
- `../mlruns` → `/mlruns`
- `../mlflow_artifacts` → `/mlflow_artifacts`

This makes it easy to examine the same files that Airflow and MLflow interact with without copying data around.
