import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import mlflow
from celery import Task

from backend.app.core.celery_app import celery_app
from backend.app.core.db import async_session
from backend.app.core.logging import get_logger
from backend.app.core.ml.config import (
    DEFAULT_PERFORMANCE_THRESHOLD,
    DEFAULT_TRAINING_LOOKBACK_DAYS,
    MLFLOW_TRACKING_URI,
)

mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

logger = get_logger()


class MLModelTrainingTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"ML Model training failed: {exc}")

        if mlflow.active_run():
            mlflow.end_run()
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(
    base=MLModelTrainingTask,
    name="train_fraud_detection_model",
    bind=True,
    max_retries=2,
    soft_time_limit=1800,
)
def train_fraud_detection_model(
    self,
    days_lookback: int = DEFAULT_TRAINING_LOOKBACK_DAYS,
    hyperparams: dict[str, Any] | None = None,
) -> dict:
    if mlflow.active_run():
        mlflow.end_run()

    try:
        logger.info("Starting training of gradient boosting fraud detection model")

        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=days_lookback)

        from backend.app.core.ml.training import ModelTrainer

        def setup_models():

            logger.info("All model dependencies loaded successfully")

        async def _train_model():
            async with async_session() as session:
                setup_models()

                trainer = ModelTrainer(session)

                model_record, metrics = await trainer.train_model(
                    start_date=start_date, end_date=end_date, hyperparams=hyperparams
                )

                return {
                    "model_id": str(model_record.id),
                    "model_type": "gradient_boosting",
                    "model_version": model_record.version,
                    "training_start": start_date.isoformat(),
                    "training_end": end_date.isoformat(),
                    "metrics": metrics,
                    "mlflow_run_id": model_record.mlflow_run_id,
                    "mlflow_model_uri": model_record.mlflow_model_uri,
                }

        result = asyncio.run(_train_model())

        logger.info(f"Successfully trained model {result['model_id']}")

        if mlflow.active_run():
            mlflow.end_run()

        return result
    except Exception as e:
        logger.error(f"Error training fraud detection model: {e}")

        if mlflow.active_run():
            mlflow.end_run()

        raise self.retry(exc=e, countdown=300) from e


@celery_app.task(name="auto_deploy_best_model", bind=True)
def auto_deploy_best_model(
    self, performance_threshold: float = DEFAULT_PERFORMANCE_THRESHOLD
) -> dict:

    try:
        logger.info("Looking for best fraud detection model to deploy")

        from sqlmodel import desc, select

        from backend.app.core.ml.deployment import ModelDeployer
        from backend.app.core.ml.models import MLModel, ModelStatusEnum

        async def _find_and_deploy_best_model():
            async with async_session() as session:
                stmt = (
                    select(MLModel)
                    .where(
                        MLModel.status == ModelStatusEnum.READY,
                        MLModel.auc_score >= performance_threshold,
                    )
                    .order_by(desc(MLModel.auc_score))
                    .limit(1)
                )

                result = await session.exec(stmt)

                best_model = result.first()

                deployer = ModelDeployer(session)

                current_model = await deployer.get_deployed_model()

                if not best_model:
                    with mlflow.start_run(run_name="auto_deploy_no_action"):
                        mlflow.log_param("action", "no_action")

                        mlflow.log_param(
                            "reason",
                            f"no_model_above_threshold_{performance_threshold}",
                        )
                    return {
                        "status": "no_action",
                        "message": f"No model found with AUC Score >= {performance_threshold}",
                    }

                if current_model and current_model.auc_score >= best_model.auc_score:
                    with mlflow.start_run(run_name="auto_deploy_no_action"):
                        mlflow.log_param("action", "no_action")

                        mlflow.log_param("reason", "current_model_better")

                        mlflow.log_param("current_model_id", str(current_model.id))

                        mlflow.log_param("candidate_model_id", str(best_model.id))

                        mlflow.log_metric("current_model_auc", current_model.auc_score)

                        mlflow.log_metric("candidate_model_auc", best_model.auc_score)

                    return {
                        "status": "no_action",
                        "message": f"Current model ({current_model.id}) "
                        "has better or equal performance",
                    }

                with mlflow.start_run(run_name="auto_deploy"):
                    mlflow.log_param("action", "deploy")
                    mlflow.log_param("model_id", str(best_model.id))
                    mlflow.log_metric("model_auc", best_model.auc_score)

                    if current_model:
                        mlflow.log_param("previous_model_id", str(current_model.id))
                        mlflow.log_metric("previous_model_auc", current_model.auc_score)
                        mlflow.log_metric(
                            "auc_improvement",
                            best_model.auc_score - current_model.auc_score,
                        )

                    deployed_model = await deployer.deploy_model(best_model.id)

                    mlflow.log_param("deployment_success", True)

                    mlflow.log_param(
                        "deployed_at", datetime.now(UTC).isoformat()
                    )

                return {
                    "status": "deployed",
                    "message": f"Successfully deployed new model {deployed_model.id}",
                    "model": {
                        "id": str(deployed_model.id),
                        "name": deployed_model.name,
                        "version": deployed_model.version,
                        "auc_score": deployed_model.auc_score,
                    },
                }

        result = asyncio.run(_find_and_deploy_best_model())

        logger.info(f"Auto-deploy task completed: {result['status']}")

        return result

    except Exception as e:
        logger.error(f"Error in auto-deploy task: {e}")
        raise
