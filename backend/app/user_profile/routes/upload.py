from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.celery_app import celery_app
from backend.app.core.db import get_session
from backend.app.core.exceptions import ValidationFailedError
from backend.app.core.logging import get_logger
from backend.app.core.utils.image import validate_image
from backend.app.user_profile.enums import ImageTypeEnum
from backend.app.user_profile.service import (
    initiate_image_upload,
    update_profile_image_url,
)

router = APIRouter(prefix="/profile")

logger = get_logger()


@router.post("/upload/{image_type}", status_code=status.HTTP_202_ACCEPTED)
async def upload_profile_image(
    image_type: ImageTypeEnum,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    """Validate the image and queue the async Cloudinary upload."""
    file_content = await file.read()
    is_valid, error_message = validate_image(file_content)

    if not is_valid:
        raise ValidationFailedError(error_message or "Invalid image")

    task_id = initiate_image_upload(
        file_content,
        image_type,
        file.content_type or "application/octet-stream",
        current_user.id,
    )
    return {
        "message": "Image upload scheduled",
        "task_id": task_id,
        "status": "pending",
    }


@router.get("/upload/{task_id}/status", status_code=status.HTTP_200_OK)
async def get_upload_status(
    task_id: str,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Poll the Celery upload task; persists the URL once it finishes."""
    task = celery_app.AsyncResult(task_id)

    if task.ready():
        if task.successful():
            result = task.get()
            logger.debug(f"Task result: {result}")

            if not isinstance(result, dict):
                raise ValidationFailedError(f"Unexpected result type: {type(result)}")

            if not result.get("url") or not result.get("image_type"):
                raise ValidationFailedError("Missing required fields in task result")

            await update_profile_image_url(
                user_id=current_user.id,
                image_type=ImageTypeEnum(result["image_type"]),
                image_url=result["url"],
                session=session,
            )

            return {
                "status": "completed",
                "image_url": result["url"],
                "thumbnail_url": result.get("thumbnail_url"),
                "image_type": result["image_type"],
            }
        else:
            error = str(task.result) if task.result else "Unknown error occurred"
            return {"status": "failed", "error": error}

    return {"status": "pending", "task_id": task_id}
