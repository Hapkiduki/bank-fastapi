from fastapi import APIRouter, Depends, Header, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.withdrawal_alert import send_withdrawal_alert
from backend.app.transaction.schema import WithdrawalRequestSchema
from backend.app.transaction.service import process_withdrawal
from backend.app.transaction.utils import (
    get_cached_idempotent_response,
    store_idempotent_response,
    validate_idempotency_key,
)

logger = get_logger()
router = APIRouter(prefix="/bank-account")


@router.post("/withdraw", status_code=status.HTTP_201_CREATED)
async def create_withdrawal(
    withdrawal_data: WithdrawalRequestSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str = Header(
        description="Idempotency key for the withdrawal request"
    ),
):
    """Withdraw cash from an account (idempotent via Idempotency-Key)."""
    idempotency_key = validate_idempotency_key(idempotency_key)

    cached_response = await get_cached_idempotent_response(
        session, key=idempotency_key, endpoint="/withdraw"
    )
    if cached_response is not None:
        return {
            "status": "success",
            "message": "Retrieved from cache",
            "data": cached_response,
        }

    transaction, account, user = await process_withdrawal(
        account_number=withdrawal_data.account_number,
        amount=withdrawal_data.amount,
        username=withdrawal_data.username,
        description=withdrawal_data.description,
        session=session,
    )

    try:
        await send_withdrawal_alert(
            email=user.email,
            full_name=user.full_name,
            amount=transaction.amount,
            account_name=account.account_name,
            account_number=account.account_number or "Unknown",
            currency=account.currency.value,
            desciption=transaction.description,
            transaction_date=transaction.completed_at or transaction.created_at,
            reference=transaction.reference,
            balance=account.balance,
        )
    except Exception as e:
        logger.error(f"Failed to send withdrawal alert: {e}")

    response = {
        "status": "success",
        "message": "Withdrawal processed successfully",
        "data": {
            "transaction_id": str(transaction.id),
            "reference": transaction.reference,
            "amount": str(transaction.amount),
            "balance": str(transaction.balance_after),
            "status": transaction.status.value,
        },
    }

    await store_idempotent_response(
        session,
        key=idempotency_key,
        user_id=user.id,
        endpoint="/withdraw",
        response_code=status.HTTP_201_CREATED,
        response_body=response,
    )

    return response
