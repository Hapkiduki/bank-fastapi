from decimal import Decimal

from fastapi import APIRouter, Depends, Header, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.transfer_alert import send_transfer_alert
from backend.app.core.services.transfer_otp import send_transfer_otp_email
from backend.app.core.utils.number_format import format_currency
from backend.app.transaction.schema import (
    TransferOTPVerificationSchema,
    TransferRequestSchema,
    TransferResponseSchema,
)
from backend.app.transaction.service import complete_transfer, initiate_transfer
from backend.app.transaction.utils import (
    get_cached_idempotent_response,
    store_idempotent_response,
    validate_idempotency_key,
)

logger = get_logger()
router = APIRouter(prefix="/bank-account")


def _transfer_summary(transaction) -> dict:
    """Common response payload for both transfer steps."""
    metadata = transaction.transaction_metadata or {}
    return {
        "reference": transaction.reference,
        "amount": format_currency(str(transaction.amount)),
        "converted_amount": metadata.get("converted_amount", "N/A"),
        "from_currency": metadata.get("from_currency", "N/A"),
        "to_currency": metadata.get("to_currency", "N/A"),
    }


@router.post(
    "/transfer/initiate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def initiate_money_transfer(
    transfer_data: TransferRequestSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str = Header(
        description="Idempotency Key for the transfer request"
    ),
) -> TransferResponseSchema:
    """Start a transfer: validates, runs fraud scoring and emails an OTP."""
    idempotency_key = validate_idempotency_key(idempotency_key)

    cached_response = await get_cached_idempotent_response(
        session,
        key=idempotency_key,
        endpoint="/transfer/initiate",
        user_id=current_user.id,
    )
    if cached_response is not None:
        return TransferResponseSchema(
            status="success",
            message="Retrieved from cache",
            data=cached_response,
        )

    transaction, sender_account, receiver_account, sender, receiver = (
        await initiate_transfer(
            sender_id=current_user.id,
            sender_account_id=transfer_data.sender_account_id,
            receiver_account_number=transfer_data.receiver_account_number,
            amount=transfer_data.amount,
            description=transfer_data.description,
            security_answer=transfer_data.security_answer,
            session=session,
        )
    )
    try:
        await send_transfer_otp_email(sender.email, sender.otp)
    except Exception as e:
        logger.error(f"Failed to send OTP email: {e}")

    response = TransferResponseSchema(
        status="pending",
        message="Transfer initiated. Please check your email for OTP verification",
        data=_transfer_summary(transaction),
    )

    await store_idempotent_response(
        session,
        key=idempotency_key,
        user_id=current_user.id,
        endpoint="/transfer/initiate",
        response_code=status.HTTP_202_ACCEPTED,
        response_body=response.model_dump(),
    )
    return response


@router.post(
    "/transfer/complete",
    status_code=status.HTTP_200_OK,
)
async def complete_money_transfer(
    verification_data: TransferOTPVerificationSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> TransferResponseSchema:
    """Finish a transfer after OTP verification; balances move here."""
    transaction, sender_account, receiver_account, sender, receiver = (
        await complete_transfer(
            reference=verification_data.transfer_reference,
            otp=verification_data.otp,
            session=session,
        )
    )

    metadata = transaction.transaction_metadata or {}
    try:
        await send_transfer_alert(
            sender_email=sender.email,
            receiver_email=receiver.email,
            sender_name=sender.full_name,
            receiver_name=receiver.full_name,
            sender_account_number=sender_account.account_number or "Unknown",
            receiver_account_number=receiver_account.account_number or "Unknown",
            amount=transaction.amount,
            converted_amount=Decimal(metadata.get("converted_amount", "0")),
            sender_currency=sender_account.currency,
            receiver_currency=receiver_account.currency,
            exchange_rate=Decimal(metadata.get("conversion_rate", "1")),
            conversion_fee=Decimal(metadata.get("conversion_fee", "0")),
            description=transaction.description,
            reference=transaction.reference,
            transaction_date=transaction.completed_at or transaction.created_at,
            sender_balance=sender_account.balance,
            receiver_balance=receiver_account.balance,
        )
    except Exception as e:
        logger.error(f"Failed to send transfer alerts: {e}")

    return TransferResponseSchema(
        status="success",
        message="Transfer completed successfully",
        data=_transfer_summary(transaction),
    )
