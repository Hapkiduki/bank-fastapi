from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.user_profile.models import Profile
from backend.app.user_profile.schema import ProfileUpdateSchema
from backend.app.user_profile.service import update_user_profile

logger = get_logger()

router = APIRouter(prefix="/profile")


@router.patch("/update", status_code=status.HTTP_200_OK)
async def update_profile(
    profile_data: ProfileUpdateSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Profile:
    profile = await update_user_profile(
        user_id=current_user.id, profile_data=profile_data, session=session
    )

    logger.info(f"Profile updated for the user {current_user.id}")
    return profile
