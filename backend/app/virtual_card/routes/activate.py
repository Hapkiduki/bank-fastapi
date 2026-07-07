from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.card_activated import send_card_activated_email
from backend.app.virtual_card.service import activate_virtual_card

logger = get_logger()
router = APIRouter(prefix="/virtual-card")


@router.patch(
    "/{card_id}/activate",
    status_code=status.HTTP_200_OK,
    description="Activate a virtual card. Only account executives can perform this action",
)
async def activate_card(
    card_id: UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """Activate a card; the CVV is emailed to the owner exactly once."""
    card, card_owner, cvv = await activate_virtual_card(
        card_id=card_id, activated_by=current_user.id, session=session
    )

    try:
        await send_card_activated_email(
            email=card_owner.email,
            full_name=card_owner.full_name,
            card_type=card.card_type.value,
            currency=card.currency.value,
            masked_card_number=card.masked_card_number,
            cvv=cvv,
            expiry_date=card.expiry_date.strftime("%m/%Y"),
            daily_limit=card.daily_limit,
            monthly_limit=card.monthly_limit,
            available_balance=card.available_balance,
        )
    except Exception as email_error:
        logger.error(f"Failed to send card activation email: {email_error}")

    return {
        "status": "success",
        "message": "Card activated successfully",
        "data": {
            "card_id": str(card.id),
            "status": card.card_status.value,
            "activated_at": (
                card.card_metadata.get("activated_at") if card.card_metadata else None
            ),
        },
    }
