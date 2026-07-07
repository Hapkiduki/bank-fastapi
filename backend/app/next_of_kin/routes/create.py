from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.next_of_kin.schema import NextOfKinCreateSchema, NextOfKinReadSchema
from backend.app.next_of_kin.service import create_next_of_kin

logger = get_logger()

router = APIRouter(prefix="/next-of-kin", tags=["Next of Kin"])


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    description="Create a new next of kin. Maximum 3 per user, only one can be primary.",
)
async def create_next_of_kin_route(
    next_of_kin_data: NextOfKinCreateSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> NextOfKinReadSchema:
    next_of_kin = await create_next_of_kin(
        user_id=current_user.id, next_of_kin_data=next_of_kin_data, session=session
    )
    logger.info(
        f"User {current_user.email} created an new next of kin: {next_of_kin.full_name}"
    )
    return next_of_kin
