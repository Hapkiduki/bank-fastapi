from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.virtual_card.schema import CardDeleteResponseSchema
from backend.app.virtual_card.service import delete_virtual_card

logger = get_logger()
router = APIRouter(prefix="/virtual-card")


@router.delete(
    "/{card_id}",
    status_code=status.HTTP_200_OK,
    description="Delete a virtual card. Card must have zero balance and no physical card request",
)
async def delete_card(
    card_id: UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> CardDeleteResponseSchema:
    result = await delete_virtual_card(
        card_id=card_id, user_id=current_user.id, session=session
    )

    return CardDeleteResponseSchema(
        status="success",
        message="Virtual card deleted successfully",
        deleted_at=result["deleted_at"],
    )
