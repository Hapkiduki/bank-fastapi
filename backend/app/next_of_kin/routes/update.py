from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.next_of_kin.schema import NextOfKinReadSchema, NextOfKinUpdateSchema
from backend.app.next_of_kin.service import update_next_of_kin

logger = get_logger()
router = APIRouter(prefix="/next-of-kin")


@router.patch(
    "/{next_of_kin_id}",
    status_code=status.HTTP_200_OK,
    description="Update a next of kin. Only provided fields will be updated",
)
async def update_next_of_kin_route(
    next_of_kin_id: UUID,
    update_data: NextOfKinUpdateSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> NextOfKinReadSchema:
    next_of_kin = await update_next_of_kin(
        user_id=current_user.id,
        next_of_kin_id=next_of_kin_id,
        update_data=update_data,
        session=session,
    )
    logger.info(f"User {current_user.email} updated next of kin: {next_of_kin_id}")
    return NextOfKinReadSchema.model_validate(next_of_kin)
