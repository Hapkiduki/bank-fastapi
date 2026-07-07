from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.user_profile.models import Profile
from backend.app.user_profile.schema import ProfileCreateSchema
from backend.app.user_profile.service import create_user_profile

logger = get_logger()

router = APIRouter(prefix="/profile")


@router.post(
    "/create", response_model=ProfileCreateSchema, status_code=status.HTTP_201_CREATED
)
async def create_profile(
    profile_data: ProfileCreateSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Profile:
    profile = await create_user_profile(
        user_id=current_user.id, profile_data=profile_data, session=session
    )

    logger.info(f"Created profile for {current_user.email}")
    return profile
