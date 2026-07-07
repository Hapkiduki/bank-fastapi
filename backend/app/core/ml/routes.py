from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import mlflow
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.auth.schema import RoleChoicesSchema
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.ml.config import ml_settings
from backend.app.core.ml.deployment import ModelDeployer
from backend.app.core.ml.evaluation import ModelEvaluator
from backend.app.core.ml.models import MLModel, ModelStatusEnum
from backend.app.core.ml.training import ModelTrainer
from backend.app.core.tasks.ml import (
    auto_deploy_best_model,
    train_fraud_detection_model,
)

logger = get_logger()

router = APIRouter(prefix="/ml", tags=["Machine Learning"])


class TrainingRequest(BaseModel):
    days_lookback: int = Field(
        default=ml_settings.DEFAULT_TRAINING_LOOKBACK_DAYS,
        description="Number of days to look back for training data",
    )
    hyperparams: dict[str, Any] | None = Field(
        default=None, description="Hyperparameters for the model"
    )
    run_async: bool = Field(
        default=True,
        description="Whether to run the training asynchronously as a background task",
    )


class ModelResponse(BaseModel):
    id: UUID
    name: str
    version: str
    status: str
    auc_score: float
    precision: float
    recall: float
    f1_score: float
    created_at: datetime
    trained_at: datetime | None = None
    deployed_at: datetime | None = None
    mlflow_run_id: str | None = None
    mlflow_model_uri: str | None = None


class TrainingResponse(BaseModel):
    model: ModelResponse | None = None
    metrics: dict[str, Any] | None = None
    mlflow_ui_url: str
    task_id: str | None = None
    status: str
    message: str


class EvaluationRequest(BaseModel):
    model_id: UUID
    start_date: datetime | None = None
    end_date: datetime | None = None


class EvaluationResponse(BaseModel):
    model_id: UUID
    metrics: dict[str, Any]
    mlflow_ui_url: str


class DeploymentRequest(BaseModel):
    model_id: UUID


class DeploymentResponse(BaseModel):
    model: ModelResponse
    status: str
    message: str
    mlflow_ui_url: str


def model_to_response(model: MLModel) -> ModelResponse:
    return ModelResponse(
        id=model.id,
        name=model.name,
        version=model.version,
        status=model.status.value,
        auc_score=model.auc_score,
        precision=model.precision,
        recall=model.recall,
        f1_score=model.f1_score,
        created_at=model.created_at,
        trained_at=model.trained_at,
        deployed_at=model.deployed_at,
        mlflow_run_id=model.mlflow_run_id,
        mlflow_model_uri=model.mlflow_model_uri,
    )


def admin_required(current_user: CurrentUser):
    if current_user.role != RoleChoicesSchema.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"status": "error", "message": "Admin access required"},
        )
    return current_user


@router.post(
    "/train/default",
    response_model=TrainingResponse,
    dependencies=[Depends(admin_required)],
)
async def train_model_with_defaults(session: AsyncSession = Depends(get_session)):
    request = TrainingRequest()

    mlflow.set_tracking_uri(ml_settings.MLFLOW_TRACKING_URI)

    task = train_fraud_detection_model.delay(
        days_lookback=request.days_lookback, hyperparams=request.hyperparams
    )

    return TrainingResponse(
        model=None,
        metrics=None,
        mlflow_ui_url="http://mlflow.localhost/",
        task_id=task.id,
        status="training_started",
        message="Model training started in the background with default settings",
    )


@router.post(
    "/train", response_model=TrainingResponse, dependencies=[Depends(admin_required)]
)
async def train_model(
    request: TrainingRequest, session: AsyncSession = Depends(get_session)
):
    mlflow.set_tracking_uri(ml_settings.MLFLOW_TRACKING_URI)

    if request.run_async:
        task = train_fraud_detection_model.delay(
            days_lookback=request.days_lookback, hyperparams=request.hyperparams
        )
        return TrainingResponse(
            model=None,
            metrics=None,
            mlflow_ui_url="http://mlflow.localhost/",
            task_id=task.id,
            status="training_started",
            message="Model training started in the background. Check task status for updates.",
        )

    trainer = ModelTrainer(session)

    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=request.days_lookback)

    try:
        model_record, metrics = await trainer.train_model(
            start_date=start_date, end_date=end_date, hyperparams=request.hyperparams
        )

        return TrainingResponse(
            model=model_to_response(model_record),
            metrics=metrics,
            mlflow_ui_url="http://mlflow.localhost/experiments/{trainer.experiment_id}",
            status="success",
            message="Model trained successfully",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error training model: {str(e)}"
        ) from e


@router.get(
    "/models",
    response_model=list[ModelResponse],
    dependencies=[Depends(admin_required)],
)
async def list_models(
    status: str | None = None,
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
):

    from sqlmodel import desc, select

    query = select(MLModel).order_by(desc(MLModel.created_at)).limit(limit)

    if status:
        try:
            status_enum = ModelStatusEnum(status)
            query = query.where(MLModel.status == status_enum)
        except ValueError:
            raise HTTPException(  # noqa: B904
                status_code=400,
                detail=f"Invalid status. Valid values are: {[s.value for s in ModelStatusEnum]}",
            )

    result = await session.exec(query)
    models = result.all()

    return [model_to_response(model) for model in models]


@router.get(
    "/models/{model_id}",
    response_model=ModelResponse,
    dependencies=[Depends(admin_required)],
)
async def get_model(model_id: UUID, session: AsyncSession = Depends(get_session)):
    model = await session.get(MLModel, model_id)

    if not model:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
    return model_to_response(model)


@router.get(
    "/status", response_model=dict[str, Any], dependencies=[Depends(admin_required)]
)
async def get_ml_status(session: AsyncSession = Depends(get_session)) -> dict:
    deployer = ModelDeployer(session)
    deployed_model = await deployer.get_deployed_model()

    from sqlmodel import func, select

    status_counts = {}

    for status_enum in ModelStatusEnum:
        stmt = select(func.count()).where(MLModel.status == status_enum)
        result = await session.exec(stmt)
        count = result.one()
        status_counts[status_enum.value] = count

    return {
        "has_deployed_model": deployed_model is not None,
        "model_details": (
            {
                "id": str(deployed_model.id),
                "name": deployed_model.name,
                "version": deployed_model.version,
                "metrics": {
                    "auc": deployed_model.auc_score,
                    "precision": deployed_model.precision,
                    "recall": deployed_model.recall,
                    "f1_score": deployed_model.f1_score,
                },
                "deployed_at": (
                    deployed_model.deployed_at.isoformat()
                    if deployed_model.deployed_at
                    else None
                ),
            }
            if deployed_model
            else None
        ),
        "model_counts": status_counts,
        "mlflow_url": "http://mlflow.localhost/",
    }


@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    dependencies=[Depends(admin_required)],
)
async def evaluate_model(
    request: EvaluationRequest, session: AsyncSession = Depends(get_session)
):

    mlflow.set_tracking_uri(ml_settings.MLFLOW_TRACKING_URI)

    evaluator = ModelEvaluator(session)

    try:
        results = await evaluator.evaluate_model_performance(
            model_id=request.model_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        return {
            "model_id": request.model_id,
            "metrics": results,
            "mlflow_ui_url": f"http://mlflow.localhost/experiments/{evaluator.experiment_id}",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error evaluating model: {str(e)}"
        ) from e


@router.post(
    "/deploy",
    response_model=DeploymentResponse,
    dependencies=[Depends(admin_required)],
)
async def deploy_model(
    request: DeploymentRequest, session: AsyncSession = Depends(get_session)
):

    mlflow.set_tracking_uri(ml_settings.MLFLOW_TRACKING_URI)

    deployer = ModelDeployer(session)

    try:
        model = await deployer.deploy_model(model_id=request.model_id)

        return {
            "model": model_to_response(model),
            "status": "deployed",
            "message": f"Model {request.model_id} deployed successfully",
            "mlflow_ui_url": f"http://mlflow.localhost/models/{ml_settings.MLFLOW_MODEL_REGISTRY_NAME}",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error deploying model: {str(e)}"
        ) from e


@router.post(
    "/auto-deploy",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(admin_required)],
)
async def trigger_auto_deploy(performance_threshold: float = 0.0) -> dict:

    task = auto_deploy_best_model.delay(performance_threshold)

    return {
        "status": "success",
        "message": "Auto-deploy task started",
        "task_id": task.id,
    }
