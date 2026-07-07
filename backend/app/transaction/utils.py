"""Transaction helpers: failure bookkeeping and idempotency-key handling."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.core.exceptions import ValidationFailedError
from backend.app.core.logging import get_logger
from backend.app.transaction.enums import (
    TransactionFailureReason,
    TransactionStatusEnum,
)
from backend.app.transaction.models import IdempotencyKey, Transaction

logger = get_logger()


def validate_idempotency_key(value: str) -> str:
    """Require the ``Idempotency-Key`` header to be a canonical UUID v4."""
    try:
        uuid_obj = uuid.UUID(value, version=4)
        if str(uuid_obj) != value.lower():
            raise ValueError("Not a valid UUID v4")
        return value
    except (ValueError, AttributeError, TypeError):
        raise ValidationFailedError(
            "Idempotency-Key must be a valid UUID v4"
        ) from None


async def get_cached_idempotent_response(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Return the stored response body for a previously-seen idempotency key.

    ``None`` means the key has not been used (or has expired) and the
    operation should proceed normally.
    """
    statement = select(IdempotencyKey).where(
        IdempotencyKey.key == key,
        IdempotencyKey.endpoint == endpoint,
        IdempotencyKey.expires_at > datetime.now(UTC),
    )
    if user_id is not None:
        statement = statement.where(IdempotencyKey.user_id == user_id)

    result = await session.exec(statement)
    existing_key = result.first()
    return existing_key.response_body if existing_key else None


async def store_idempotent_response(
    session: AsyncSession,
    *,
    key: str,
    user_id: uuid.UUID,
    endpoint: str,
    response_code: int,
    response_body: dict[str, Any],
    ttl_hours: int = 24,
) -> None:
    """Persist a response body under an idempotency key and commit."""
    record = IdempotencyKey(
        key=key,
        user_id=user_id,
        endpoint=endpoint,
        response_code=response_code,
        response_body=response_body,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    session.add(record)
    await session.commit()


async def mark_transaction_failed(
    transaction: Transaction,
    reason: TransactionFailureReason,
    details: dict,
    session: AsyncSession,
    error_message: str | None = None,
) -> None:
    try:
        transaction.status = TransactionStatusEnum.Failed

        transaction.failed_reason = reason.value

        current_metadata = transaction.transaction_metadata or {}

        failure_details = {
            "reason": reason.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "error_message": error_message,
            **details,
        }

        transaction.transaction_metadata = {
            **current_metadata,
            "failure_details": failure_details,
        }

        session.add(transaction)

        await session.commit()

        await session.refresh(transaction)

        logger.error(
            f"Transaction {transaction.reference} failed",
            extra={
                "reference": transaction.reference,
                "reason": reason.value,
                "details": failure_details,
            },
        )
    except Exception as e:
        logger.error(f"Error marking transaction as failed: {e}")

        raise
