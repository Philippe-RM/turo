import ray
from sklearn.model_selection import KFold
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error, explained_variance_score, max_error
import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.preprocessing import StandardScaler
import mlflow

# Initialiser Ray
ray.init(address="auto", ignore_reinit_error=True)

@ray.remote
def evaluate_fold(train_index, test_index, X, y, params):
    X_train, X_test = X.iloc[train_index], X.iloc[test_index]
    y_train, y_test = y.iloc[train_index], y.iloc[test_index]

    # Normaliser les données
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = XGBRegressor(**params)
    model.fit(X_train_scaled, y_train)
    y_pred = model.predict(X_test_scaled)

    mse = mean_squared_error(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    r2 = r2_score(y_test, y_pred)
    explained_variance = explained_variance_score(y_test, y_pred)
    max_err = max_error(y_test, y_pred)

    return {
        "mse": mse,
        "mae": mae,
        "rmse": rmse,
        "r2_score": r2,
        "explained_variance": explained_variance,
        "max_error": max_err,
    }

def main():
    # Load dataset
    data = pd.read_csv('/app/datas/datas.csv')
    X = data.drop('target', axis=1)
    y = data['target']

    # Define the model parameters
    params = {"n_estimators": 100, "max_depth": 3, "learning_rate": 0.1, "random_state": 42}

    # Define KFold for cross-validation
    kf = KFold(n_splits=5, shuffle=True, random_state=42)

    # Perform cross-validation in parallel
    results = []
    for train_index, test_index in kf.split(X):
        results.append(evaluate_fold.remote(train_index, test_index, X, y, params))

    # Collect results
    cv_results = ray.get(results)

    # Calculate mean metrics
    mean_mse = np.mean([res["mse"] for res in cv_results])
    mean_mae = np.mean([res["mae"] for res in cv_results])
    mean_rmse = np.mean([res["rmse"] for res in cv_results])
    mean_r2 = np.mean([res["r2_score"] for res in cv_results])
    mean_explained_variance = np.mean([res["explained_variance"] for res in cv_results])
    mean_max_error = np.mean([res["max_error"] for res in cv_results])

    # Normaliser les données complètes
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train final model on full dataset
    model = XGBRegressor(**params)
    model.fit(X_scaled, y)

    # Log metrics and model with MLflow
    with mlflow.start_run():
        mlflow.log_params(params)
        mlflow.log_metric("mean_cv_mse", mean_mse)
        mlflow.log_metric("mean_cv_mae", mean_mae)
        mlflow.log_metric("mean_cv_rmse", mean_rmse)
        mlflow.log_metric("mean_cv_r2_score", mean_r2)
        mlflow.log_metric("mean_cv_explained_variance", mean_explained_variance)
        mlflow.log_metric("mean_cv_max_error", mean_max_error)
        # Create an input example from the first row of X as a DataFrame
        input_example = X.iloc[[0]]
        mlflow.xgboost.log_model(model, "model", input_example=input_example)

if __name__ == "__main__":
    main()
