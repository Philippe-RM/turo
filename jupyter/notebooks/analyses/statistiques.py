# Import necessary modules
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.linear_model import LinearRegression, Ridge, Lasso
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
from sklearn.svm import SVR
from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
from catboost import CatBoostRegressor
from sklearn.neighbors import KNeighborsRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GridSearchCV
from scikeras.wrappers import KerasRegressor

# Load CSV files
vehicles_df = pd.read_csv('../vehicles.csv')
reservations_df = pd.read_csv('../reservations.csv')

# Display the first few rows of each dataframe to understand their structure
display(vehicles_df.head())
display(reservations_df.head())

# Aggregate the reservations data to get the total number of reservations per vehicle
reservations_count = reservations_df['vehicle_id'].value_counts().reset_index()
reservations_count.columns = ['vehicle_id', 'total_reservations']

# Merge the aggregated reservations data with the vehicles data
merged_data = pd.merge(vehicles_df, reservations_count, on='vehicle_id', how='left')
merged_data['total_reservations'] = merged_data['total_reservations'].fillna(0)

# Display the first few rows of the merged data
display(merged_data.head())

# Calculate descriptive statistics for each column
descriptive_stats = merged_data.describe()

# Display descriptive statistics
print("Descriptive Statistics:")
display(descriptive_stats)

# Plot box plots for each column to identify outliers
plt.figure(figsize=(15, 10))
for i, column in enumerate(merged_data.columns):
    if merged_data[column].dtype in [np.dtype('int64'), np.dtype('float64')]:
        plt.subplot(3, 3, i+1)
        sns.boxplot(y=merged_data[column])
        plt.title(column)
plt.tight_layout()
plt.show()

# Plot histograms for each column to understand the distribution
plt.figure(figsize=(15, 10))
for i, column in enumerate(merged_data.columns):
    if merged_data[column].dtype in [np.dtype('int64'), np.dtype('float64')]:
        plt.subplot(3, 3, i+1)
        sns.histplot(merged_data[column], kde=True)
        plt.title(column)
plt.tight_layout()
plt.show()

# Convert 'created_at' to datetime
reservations_df['created_at'] = pd.to_datetime(reservations_df['created_at'])

# Extract year, month, and day for analysis
reservations_df['year'] = reservations_df['created_at'].dt.year
reservations_df['month'] = reservations_df['created_at'].dt.month
reservations_df['day'] = reservations_df['created_at'].dt.day

# Calculate the time period covered by the data
min_date = reservations_df['created_at'].min()
max_date = reservations_df['created_at'].max()
time_period = max_date - min_date

# Display the time period
print("Time Period Covered by Reservations Data:")
print(f"From: {min_date}")
print(f"To: {max_date}")
print(f"Total Duration: {time_period.days} days")

# Plot the distribution of reservations over time
plt.figure(figsize=(15, 5))
reservations_df['created_at'].hist(bins=50, edgecolor='black')
plt.title('Distribution of Reservations Over Time')
plt.xlabel('Date')
plt.ylabel('Number of Reservations')
plt.show()

# Calculate Pearson correlation matrix
pearson_correlation_matrix = merged_data.corr(method='pearson')

# Calculate Spearman correlation matrix
spearman_correlation_matrix = merged_data.corr(method='spearman')

# Filter and sort correlations with 'total_reservations' having absolute value > 0.2 for Pearson
pearson_correlation_with_total_reservations = pearson_correlation_matrix['total_reservations']
significant_pearson_correlations = pearson_correlation_with_total_reservations[abs(pearson_correlation_with_total_reservations) > 0.02]
significant_pearson_correlations = significant_pearson_correlations.abs().sort_values(ascending=False)

# Filter and sort correlations with 'total_reservations' having absolute value > 0.2 for Spearman
spearman_correlation_with_total_reservations = spearman_correlation_matrix['total_reservations']
significant_spearman_correlations = spearman_correlation_with_total_reservations[abs(spearman_correlation_with_total_reservations) > 0.02]
significant_spearman_correlations = significant_spearman_correlations.abs().sort_values(ascending=False)

# Display significant correlations
print("Variables with Pearson correlation > 0.2 with total_reservations (sorted by absolute value):")
print(significant_pearson_correlations)
print("\nVariables with Spearman correlation > 0.2 with total_reservations (sorted by absolute value):")
print(significant_spearman_correlations)

# Plotting the Pearson correlation matrix
plt.figure(figsize=(10, 8))
sns.heatmap(pearson_correlation_matrix, annot=True, cmap='coolwarm', fmt=".2f")
plt.title('Pearson Correlation Matrix')
plt.show()

# Plotting the Spearman correlation matrix
plt.figure(figsize=(10, 8))
sns.heatmap(spearman_correlation_matrix, annot=True, cmap='coolwarm', fmt=".2f")
plt.title('Spearman Correlation Matrix')
plt.show()

# Identify significant features based on Pearson correlation
significant_features = significant_pearson_correlations.index.tolist()
significant_features.remove('total_reservations')  # Remove the target variable

merged_data_significant_features = merged_data[significant_features].copy()
merged_data_significant_features['target'] = merged_data['total_reservations']

# Define features and target variable using only significant features
X = merged_data_significant_features.drop(columns=['target'])
y = merged_data_significant_features['target']

display(X)

# Split the data into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)


# Scale the data for deep learning
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Initialize and train the linear regression model
model = LinearRegression()
model.fit(X_train_scaled, y_train)

# Make predictions on the test set
y_pred = model.predict(X_test_scaled)

# Evaluate the model
mse = mean_squared_error(y_test, y_pred)
rmse = np.sqrt(mse)
mae = mean_absolute_error(y_test, y_pred)
mape = np.mean(np.abs((y_test - y_pred) / y_test)) * 100
r2 = r2_score(y_test, y_pred)
n = len(y_test)
p = len(significant_features)
adjusted_r2 = 1 - (1 - r2) * (n - 1) / (n - p - 1)

print(f'Mean Squared Error (MSE): {mse}')
print(f'Root Mean Squared Error (RMSE): {rmse}')
print(f'Mean Absolute Error (MAE): {mae}')
print(f'Mean Absolute Percentage Error (MAPE): {mape}%')
print(f'R-squared (R²): {r2}')
print(f'Adjusted R-squared: {adjusted_r2}')


# Plot measured vs expected values
plt.figure(figsize=(10, 6))
plt.scatter(y_test, y_pred, alpha=0.5)
plt.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], 'k--', lw=2)  # Line y = x
plt.xlabel('Measured (Actual) Values')
plt.ylabel('Expected (Predicted) Values')
plt.title('Measured vs Expected Values')
plt.show()


# Define models and parameter grids for GridSearchCV
models = {
    "SVR": {
        "model": SVR(),
        "params": {
            'kernel': ['linear', 'rbf'],
            'C': [0.05, 0.1, 0.2],  # Around previous best: 0.1
            'epsilon': [0.05, 0.1, 0.15],  # Around previous best: 0.1
            'gamma': ['scale', 'auto', 0.1, 1]  # Adding specific gamma values
        }
    },
    "XGBoost": {
        "model": XGBRegressor(random_state=42),
        "params": {
            'n_estimators': np.linspace(90, 120, 3, dtype=int),
            'max_depth': [1, 2, 3],
            'learning_rate': np.linspace(0.025, 0.05, 3),
            'subsample': np.linspace(0.6, 0.8, 3),
            'colsample_bytree': np.linspace(0.6, 0.8, 5),
            'reg_alpha': np.linspace(0.02, 0.1, 3),
            'reg_lambda': np.linspace(0.02, 0.1, 3)
        }
    },
    "CatBoost": {
        "model": CatBoostRegressor(random_state=42, silent=True),
        "params": {
            'iterations': np.linspace( 120, 150, 2, dtype=int),
            'depth': [2, 3, 4],
            'learning_rate': np.linspace(0.001, 0.02, 3),
            'l2_leaf_reg': np.linspace(0.5, 0.7, 10),
            'bagging_temperature': np.linspace(0, 0.1, 3)
        }
    },
    "KNN": {
        "model": KNeighborsRegressor(),
        "params": {
            'n_neighbors': np.linspace(13, 40, 5, dtype=int),
            'weights': ['uniform', 'distance'],
            'p': [2, 3, 4,5,6,7,8,9,10]
        }
    },

    
}


# Perform GridSearchCV for each model
results = []
for name, config in models.items():
    if name == "Neural Network":
        grid_search = GridSearchCV(config["model"], config["params"], cv=5, scoring='neg_mean_squared_error', n_jobs=-1)
    else:
        grid_search = GridSearchCV(config["model"], config["params"], cv=5, scoring='neg_mean_squared_error', n_jobs=-1)
    grid_search.fit(X_train_scaled if name == "Neural Network" else X_train, y_train)
    best_model = grid_search.best_estimator_
    y_pred = best_model.predict(X_test_scaled if name == "Neural Network" else X_test)
    mse = mean_squared_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    results.append({
        "Model": name,
        "Best Params": grid_search.best_params_,
        "MSE": mse,
        "RMSE": rmse,
        "MAE": mae,
        "R2": r2
    })

# Display results with full column width
pd.set_option('display.max_colwidth', None)
results_df = pd.DataFrame(results)
display(results_df)

from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.layers import Dense, Dropout, BatchNormalization
import tensorflow as tf
from tensorflow.keras import Sequential, layers, regularizers, callbacks, optimizers

# Create a simple neural network model
model = Sequential([
    Dense(128, activation='relu', input_shape=(X_train_scaled.shape[1],)),
    Dense(64, activation='relu'),  # Using tanh activation
    Dense(32, activation='relu'),
    Dense(16, activation='relu'),  # Using tanh activation
    Dense(1)  # Output layer for regression
])

# Compile the model
model.compile(optimizer=Adam(learning_rate=0.0001), loss='mse')

# Train the model
history = model.fit(X_train_scaled, y_train, epochs=150, batch_size=32, validation_split=0.2, verbose=1)

# Plot training history
plt.figure(figsize=(10, 5))
plt.plot(history.history['loss'], label='Training Loss')
plt.plot(history.history['val_loss'], label='Validation Loss')
plt.title('Model Loss')
plt.ylabel('Loss')
plt.xlabel('Epoch')
plt.legend()
plt.show()

# Evaluate the model on the test set
y_pred = model.predict(X_test_scaled).flatten()

# Calculate metrics
mse = mean_squared_error(y_test, y_pred)
rmse = np.sqrt(mse)
mae = mean_absolute_error(y_test, y_pred)
r2 = r2_score(y_test, y_pred)

print(f'Mean Squared Error (MSE): {mse}')
print(f'Root Mean Squared Error (RMSE): {rmse}')
print(f'Mean Absolute Error (MAE): {mae}')
print(f'R-squared (R²): {r2}')

# Plot measured vs expected values
plt.figure(figsize=(10, 6))
plt.scatter(y_test, y_pred, alpha=0.5)
plt.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], 'k--', lw=2)
plt.xlabel('Measured (Actual) Values')
plt.ylabel('Expected (Predicted) Values')
plt.title('Measured vs Expected Values (Neural Network)')
plt.show()


# Calculate mean and standard deviation of the target variable 'total_reservations'
mean_total_reservations = merged_data['total_reservations'].mean()
std_total_reservations = merged_data['total_reservations'].std()

# Display mean and standard deviation
print("Descriptive Statistics for 'total_reservations':")
print(f"Mean: {mean_total_reservations}")
print(f"Standard Deviation: {std_total_reservations}")

# Calculate additional statistics for better context
min_total_reservations = merged_data['total_reservations'].min()
max_total_reservations = merged_data['total_reservations'].max()
median_total_reservations = merged_data['total_reservations'].median()

print(f"Minimum: {min_total_reservations}")
print(f"Maximum: {max_total_reservations}")
print(f"Median: {median_total_reservations}")

# Plot the distribution of 'total_reservations'
plt.figure(figsize=(10, 5))
sns.histplot(merged_data['total_reservations'], kde=True, bins=30)
plt.title('Distribution of Total Reservations')
plt.xlabel('Total Reservations')
plt.ylabel('Frequency')
plt.show()
