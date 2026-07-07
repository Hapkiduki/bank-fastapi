import os
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class MLSettings(BaseSettings):
    MLFLOW_TRACKING_URI: str = os.environ.get(
        "MLFLOW_TRACKING_URI", "http://mlflow:4000"
    )
    MLFLOW_EXPERIMENT_NAME: str = "fraud_detection"
    MLFLOW_MODEL_REGISTRY_NAME: str = "fraud_detection_models"
    MODEL_STORAGE_PATH: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "models"
    )

    DATASET_STORAGE_PATH: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "datasets"
    )

    DEFAULT_TRAINING_LOOKBACK_DAYS: int = 90

    DEFAULT_PERFORMANCE_THRESHOLD: float = 0.85

    DEFAULT_GRADIENT_BOOSTING_PARAMS: dict[str, Any] = {
        "n_estimators": 100,
        "learning_rate": 0.1,
        "max_depth": 3,
        "min_samples_split": 2,
        "min_samples_leaf": 1,
        "subsample": 0.8,
        "random_state": 42,
    }

    DEFAULT_RISK_THRESHOLD: float = 0.7
    HIGH_RISK_THRESHOLD: float = 0.85

    model_config = SettingsConfigDict(
        env_file="../../.envs/.env.local",
        env_ignore_empty=True,
        extra="ignore",
        env_prefix="ML_",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        os.makedirs(self.MODEL_STORAGE_PATH, exist_ok=True)
        os.makedirs(self.DATASET_STORAGE_PATH, exist_ok=True)


ml_settings = MLSettings()

MLFLOW_TRACKING_URI = ml_settings.MLFLOW_TRACKING_URI

MLFLOW_EXPERIMENT_NAME = ml_settings.MLFLOW_EXPERIMENT_NAME

MLFLOW_MODEL_REGISTRY_NAME = ml_settings.MLFLOW_MODEL_REGISTRY_NAME

MODEL_STORAGE_PATH = ml_settings.MODEL_STORAGE_PATH

DATASET_STORAGE_PATH = ml_settings.DATASET_STORAGE_PATH
DEFAULT_TRAINING_LOOKBACK_DAYS = ml_settings.DEFAULT_TRAINING_LOOKBACK_DAYS

DEFAULT_PERFORMANCE_THRESHOLD = ml_settings.DEFAULT_PERFORMANCE_THRESHOLD

DEFAULT_GRADIENT_BOOSTING_PARAMS = ml_settings.DEFAULT_GRADIENT_BOOSTING_PARAMS
DEFAULT_RISK_THRESHOLD = ml_settings.DEFAULT_RISK_THRESHOLD
HIGH_RISK_THRESHOLD = ml_settings.HIGH_RISK_THRESHOLD
