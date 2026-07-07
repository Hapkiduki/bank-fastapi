from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.schema import UserCreateSchema, UserReadSchema
from backend.app.auth.service import user_auth_service
from backend.app.core.db import get_session
from backend.app.core.exceptions import ValidationFailedError
from backend.app.core.logging import get_logger

logger = get_logger()

router = APIRouter(prefix="/auth")


@router.post(
    "/register",
    response_model=UserReadSchema,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    user_data: UserCreateSchema, session: AsyncSession = Depends(get_session)
):
    """Register a new user; the account stays inactive until email activation."""
    if await user_auth_service.check_user_email_exists(user_data.email, session):
        raise ValidationFailedError("User with this email already exists")

    if await user_auth_service.check_user_id_no_exists(user_data.id_no, session):
        raise ValidationFailedError("User with this id number already exists")

    new_user = await user_auth_service.create_user(user_data, session)
    logger.info(
        f"New user {new_user.email} registered successfully, awaiting activation"
    )
    return new_user
