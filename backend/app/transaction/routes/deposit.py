from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import require_role
from backend.app.auth.models import User
from backend.app.auth.schema import RoleChoicesSchema
from backend.app.core.db import get_session
from backend.app.core.exceptions import ForbiddenError
from backend.app.core.logging import get_logger
from backend.app.core.services.deposit_alert import send_deposit_alert
from backend.app.transaction.enums import TransactionTypeEnum
from backend.app.transaction.schema import DepositRequestSchema
from backend.app.transaction.service import process_deposit

logger = get_logger()

router = APIRouter(prefix="/bank-account")


@router.post("/deposit", status_code=status.HTTP_201_CREATED)
async def create_deposit(
    deposit_data: DepositRequestSchema,
    current_user: User = Depends(
        require_role(RoleChoicesSchema.TELLER, "Only tellers can process deposits")
    ),
    session: AsyncSession = Depends(get_session),
):
    """Teller-only deposit into a customer account."""
    transaction, account, account_owner = await process_deposit(
        amount=deposit_data.amount,
        account_id=deposit_data.account_id,
        teller_id=current_user.id,
        description=deposit_data.description,
        session=session,
    )

    if not account.account_number:
        raise ForbiddenError("Account number is required")

    try:
        currency_value = account.currency.value
        await send_deposit_alert(
            email=account_owner.email,
            full_name=account_owner.full_name,
            action=TransactionTypeEnum.Deposit.value,
            amount=transaction.amount,
            account_name=account.account_name,
            account_number=account.account_number,
            currency=currency_value,
            description=transaction.description,
            transaction_date=transaction.completed_at or transaction.created_at,
            reference=transaction.reference,
            balance=transaction.balance_after,
        )
    except Exception as email_error:
        logger.error(f"Failed to send transaction alert: {email_error}")

    return {
        "status": "success",
        "message": "Deposit processed successfully",
        "data": {
            "transaction_id": transaction.id,
            "reference": transaction.reference,
            "amount": transaction.amount,
            "balance": transaction.balance_after,
            "status": transaction.status,
        },
    }
