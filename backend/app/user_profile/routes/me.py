from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.user_profile.schema import ProfileResponseSchema
from backend.app.user_profile.service import get_user_with_profile

logger = get_logger()

router = APIRouter(prefix="/profile")


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_my_profile(
    current_user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> ProfileResponseSchema:
    user_with_profile = await get_user_with_profile(current_user.id, session)

    response = ProfileResponseSchema(
        username=user_with_profile.username or "",
        first_name=user_with_profile.first_name or "",
        middle_name=user_with_profile.middle_name or "",
        last_name=user_with_profile.last_name or "",
        email=user_with_profile.email or "",
        id_no=str(user_with_profile.id_no) if user_with_profile.id_no else "",
        role=user_with_profile.role,
        profile=user_with_profile.profile,
    )
    logger.debug(f"Successfully fetched profile for user {user_with_profile.id}")
    return response
