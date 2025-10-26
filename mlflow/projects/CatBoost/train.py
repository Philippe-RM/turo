import mlflow
import mlflow.catboost
from catboost import CatBoostRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error, explained_variance_score, max_error
import pandas as pd
import numpy as np

def main():
    # Load dataset
    data = pd.read_csv('/app/datas/datas.csv')
    X = data.drop('target', axis=1)
    y = data['target']

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Train CatBoost model
    model = CatBoostRegressor(bagging_temperature=0.0, depth=2, iterations=150, l2_leaf_reg=0.5, learning_rate=0.02)
    model.fit(X_train, y_train)

    # Evaluate model
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    r2 = r2_score(y_test, y_pred)
    explained_variance = explained_variance_score(y_test, y_pred)
    max_err = max_error(y_test, y_pred)

    # Log metrics and model with MLflow
    with mlflow.start_run():
        mlflow.log_param("bagging_temperature", 0.0)
        mlflow.log_param("depth", 2)
        mlflow.log_param("iterations", 150)
        mlflow.log_param("l2_leaf_reg", 0.5)
        mlflow.log_param("learning_rate", 0.02)
        mlflow.log_metric("mse", mse)
        mlflow.log_metric("mae", mae)
        mlflow.log_metric("rmse", rmse)
        mlflow.log_metric("r2_score", r2)
        mlflow.log_metric("explained_variance", explained_variance)
        mlflow.log_metric("max_error", max_err)
        # Create an input example from the first row of X_train as a DataFrame
        input_example = X_train.iloc[[0]]
        mlflow.catboost.log_model(model, "model", input_example=input_example)

if __name__ == "__main__":
    main()
