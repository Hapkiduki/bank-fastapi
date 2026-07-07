from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import require_role
from backend.app.auth.models import User
from backend.app.auth.schema import RoleChoicesSchema
from backend.app.bank_account.schema import BankAccountReadSchema
from backend.app.bank_account.service import activate_bank_account
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.bank_account_activated_email import (
    send_account_activated_email,
)

logger = get_logger()

router = APIRouter(prefix="/bank-account")


@router.patch(
    "/{account_id}/activate",
    status_code=status.HTTP_200_OK,
    description="Activate a bank account after KYC verification. "
    "Only accessible to account executives",
)
async def activate_account(
    account_id: UUID,
    current_user: User = Depends(
        require_role(
            RoleChoicesSchema.ACCOUNT_EXECUTIVE,
            "Only account executives can activate bank accounts",
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> BankAccountReadSchema:
    """KYC-verify and activate an account (executives only)."""
    activated_account, account_owner = await activate_bank_account(
        account_id=account_id, verified_by=current_user.id, session=session
    )
    try:
        if activated_account.account_number:
            await send_account_activated_email(
                email=account_owner.email,
                full_name=account_owner.full_name,
                account_number=activated_account.account_number,
                account_name=activated_account.account_name,
                account_type=activated_account.account_type.value,
                currency=activated_account.currency.value,
            )
            logger.info(f"Bank Account activated email sent to {account_owner.email}")
    except Exception as email_error:
        logger.error(f"Failed to send bank account activated email: {email_error}")

    logger.info(
        f"Bank account {account_id} activated by account executive {current_user.email}"
    )

    return BankAccountReadSchema.model_validate(activated_account)
