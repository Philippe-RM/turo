import mlflow
import mlflow.sklearn
from sklearn.svm import SVR
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
import pandas as pd

def main():
    # Load dataset
    data = pd.read_csv('/app/datas/datas.csv')
    X = data.drop('target', axis=1)
    y = data['target']

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Train SVR model
    model = SVR(C=0.05, epsilon=0.15, gamma='scale', kernel='linear')
    model.fit(X_train, y_train)

    # Evaluate model
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    # Log metrics and model with MLflow
    with mlflow.start_run():
        mlflow.log_param("C", 0.05)
        mlflow.log_param("epsilon", 0.15)
        mlflow.log_param("gamma", 'scale')
        mlflow.log_param("kernel", 'linear')
        mlflow.log_metric("mse", mse)
        mlflow.log_metric("r2_score", r2)
        mlflow.sklearn.log_model(model, "model")

if __name__ == "__main__":
    main()
