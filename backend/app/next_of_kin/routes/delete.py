from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.next_of_kin.service import delete_next_of_kin

logger = get_logger()
router = APIRouter(prefix="/next-of-kin")


@router.delete(
    "/{next_of_kin_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description="Delete a next of kin. Cannot delete if it's the only one remaining",
)
async def delete_next_of_kin_route(
    next_of_kin_id: UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    await delete_next_of_kin(
        user_id=current_user.id, next_of_kin_id=next_of_kin_id, session=session
    )
