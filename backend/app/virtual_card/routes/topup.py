from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.transaction.utils import (
    get_cached_idempotent_response,
    store_idempotent_response,
    validate_idempotency_key,
)
from backend.app.virtual_card.schema import CardTopUpResponseSchema, CardTopUpSchema
from backend.app.virtual_card.service import top_up_virtual_card

logger = get_logger()

router = APIRouter(prefix="/virtual-card")


@router.post(
    "/{card_id}/top-up",
    status_code=status.HTTP_200_OK,
    description="Top up a virtual card from a bank account. Card must be active",
)
async def top_up_card(
    card_id: UUID,
    top_up_data: CardTopUpSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str = Header(description="Idempotency key for the top-up request"),
) -> CardTopUpResponseSchema:
    """Move money from the linked bank account onto the card (idempotent)."""
    idempotency_key = validate_idempotency_key(idempotency_key)

    cached_response = await get_cached_idempotent_response(
        session,
        key=idempotency_key,
        endpoint="/virtual-card/top-up",
        user_id=current_user.id,
    )
    if cached_response is not None:
        return CardTopUpResponseSchema(
            status="success",
            message="Retrieved from cache",
            data=cached_response,
        )

    card, transaction = await top_up_virtual_card(
        card_id=card_id,
        account_number=top_up_data.account_number,
        amount=top_up_data.amount,
        description=top_up_data.description,
        session=session,
    )

    response = CardTopUpResponseSchema(
        status="success",
        message="Card topped up successfully",
        data={
            "card_id": str(card.id),
            "transaction_id": str(transaction.id),
            "amount": str(transaction.amount),
            "new_balance": str(card.available_balance),
            "reference": transaction.reference,
        },
    )

    await store_idempotent_response(
        session,
        key=idempotency_key,
        user_id=current_user.id,
        endpoint="/virtual-card/top-up",
        response_code=status.HTTP_200_OK,
        response_body=response.model_dump(),
    )

    return response
