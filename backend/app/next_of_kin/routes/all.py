from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.next_of_kin.schema import NextOfKinReadSchema
from backend.app.next_of_kin.service import get_user_next_of_kins

logger = get_logger()
router = APIRouter(prefix="/next-of-kin")


@router.get(
    "/all",
    status_code=status.HTTP_200_OK,
    description="Get all next of kins for the authenticated user",
)
async def list_next_of_kins(
    current_user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[NextOfKinReadSchema]:
    next_of_kins = await get_user_next_of_kins(user_id=current_user.id, session=session)
    return [NextOfKinReadSchema.model_validate(kin) for kin in next_of_kins]
