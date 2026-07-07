from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.card_blocked import send_card_blocked_email
from backend.app.virtual_card.schema import CardBlockSchema
from backend.app.virtual_card.service import block_virtual_card

logger = get_logger()
router = APIRouter(prefix="/virtual-card")


@router.post(
    "/{card_id}/block",
    status_code=status.HTTP_200_OK,
    description="Block a virtual card. Can be performed by card owner or account executive",
)
async def block_card(
    card_id: UUID,
    block_data: CardBlockSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    card, card_owner = await block_virtual_card(
        card_id=card_id,
        block_data=block_data.model_dump(),
        blocked_by=current_user.id,
        session=session,
    )

    try:
        await send_card_blocked_email(
            email=card_owner.email,
            full_name=card_owner.full_name,
            card_type=card.card_type.value,
            masked_card_number=card.masked_card_number,
            block_reason=str(card.block_reason.value) if card.block_reason else "",
            block_reason_description=(
                str(card.block_reason_description)
                if card.block_reason_description
                else ""
            ),
            blocked_at=card.blocked_at or datetime.now(UTC),
        )
    except Exception as email_error:
        logger.error(f"Failed to send card blocked email: {email_error}")

    return {
        "status": "success",
        "message": "Card blocked successfully",
        "data": {
            "card_id": str(card.id),
            "status": card.card_status.value,
            "block_reason": card.block_reason.value if card.block_reason else "",
            "blocked_at": (card.blocked_at.isoformat() if card.blocked_at else None),
        },
    }
