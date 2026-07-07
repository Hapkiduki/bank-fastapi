"""Business logic for virtual cards: creation, activation, block, top-up,
soft deletion. Top-ups move money out of a bank account, so the account row
is locked (``SELECT ... FOR UPDATE``) and re-validated before the debit."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.models import User
from backend.app.auth.schema import RoleChoicesSchema
from backend.app.bank_account.enums import AccountStatusEnum
from backend.app.bank_account.models import BankAccount
from backend.app.core.exceptions import (
    AccountNotActiveError,
    ForbiddenError,
    InsufficientBalanceError,
    NotFoundError,
    ValidationFailedError,
)
from backend.app.core.logging import get_logger
from backend.app.transaction.enums import (
    TransactionCategoryEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)
from backend.app.transaction.models import Transaction
from backend.app.virtual_card.enums import VirtualCardStatusEnum
from backend.app.virtual_card.models import VirtualCard
from backend.app.virtual_card.utils import (
    generate_card_expiry_date,
    generate_cvv,
    generate_visa_card_number,
)

logger = get_logger()


async def create_virtual_card(
    user_id: UUID, bank_account_id: UUID, card_data: dict, session: AsyncSession
) -> tuple[VirtualCard, User, BankAccount]:
    """Issue a new (pending) virtual card tied to an active bank account."""
    statement = (
        select(BankAccount, User)
        .join(User)
        .where(BankAccount.id == bank_account_id, BankAccount.user_id == user_id)
    )
    result = await session.exec(statement)
    account_user = result.first()

    if not account_user:
        raise NotFoundError("Bank account not found or does not belong to the user")

    bank_account, user = account_user

    if bank_account.account_status != AccountStatusEnum.Active:
        raise AccountNotActiveError("Bank account is not active")

    card_currency = card_data.get("currency")

    if card_currency != bank_account.currency:
        raise ValidationFailedError("Card currency must match the bank account currency")

    cleaned_data = card_data.copy()

    cleaned_data.pop("card_number", None)
    cleaned_data.pop("card_status", None)
    cleaned_data.pop("is_active", None)
    cleaned_data.pop("cvv_hash", None)
    cleaned_data.pop("available_balance", None)
    cleaned_data.pop("total_topped_up", None)
    cleaned_data.pop("card_metadata", None)

    card_number = generate_visa_card_number()

    if not cleaned_data.get("expiry_date"):
        expiry_date = generate_card_expiry_date()
        cleaned_data["expiry_date"] = expiry_date.date()

    card = VirtualCard(
        **cleaned_data,
        card_number=card_number,
        bank_account_id=bank_account_id,
        card_status=VirtualCardStatusEnum.Pending,
        is_active=True,
        available_balance=Decimal("0.00"),
        total_topped_up=Decimal("0.00"),
        last_top_up_date=datetime.now(UTC),
        card_metadata={
            "created_by": str(user.id),
            "created_at": datetime.now(UTC).isoformat(),
        },
    )

    session.add(card)
    await session.commit()

    await session.refresh(card)

    return card, user, bank_account


async def block_virtual_card(
    card_id: UUID, block_data: dict, blocked_by: UUID, session: AsyncSession
) -> tuple[VirtualCard, User]:
    """Block a card and record who/why in its metadata."""
    statement = (
        select(VirtualCard, User)
        .select_from(VirtualCard)
        .join(BankAccount)
        .join(User)
        .where(VirtualCard.id == card_id)
    )
    result = await session.exec(statement)
    card_data = result.first()

    if not card_data:
        raise NotFoundError("Virtual card not found")

    card, card_owner = card_data

    if card.card_status == VirtualCardStatusEnum.Blocked:
        raise ValidationFailedError("Card is already blocked")

    block_time = datetime.now(UTC)
    card.card_status = VirtualCardStatusEnum.Blocked
    card.block_reason = block_data["block_reason"]
    card.block_reason_description = block_data["block_reason_description"]
    card.blocked_by = blocked_by
    card.blocked_at = block_time
    if not card.card_metadata:
        card.card_metadata = {}

    card.card_metadata.update(
        {
            "blocked_at": block_time.isoformat(),
            "blocked_by": str(blocked_by),
            "block_reason": block_data["block_reason"].value,
        }
    )

    session.add(card)

    await session.commit()

    await session.refresh(card)

    return card, card_owner


async def top_up_virtual_card(
    card_id: UUID,
    account_number: str,
    amount: Decimal,
    description: str,
    session: AsyncSession,
) -> tuple[VirtualCard, Transaction]:
    """Move ``amount`` from the linked bank account onto the card.

    The bank account row is locked for the duration of the operation and the
    balance re-checked under the lock, mirroring the discipline used for
    transfers and withdrawals.
    """
    statement = (
        select(VirtualCard, BankAccount)
        .join(BankAccount)
        .where(VirtualCard.id == card_id, BankAccount.account_number == account_number)
    )
    result = await session.exec(statement)
    card_account = result.first()

    if not card_account:
        raise NotFoundError("Virtual card or bank account not found")

    card, bank_account = card_account

    if card.card_status != VirtualCardStatusEnum.Active:
        raise ValidationFailedError("Card is not active")

    if card.currency != bank_account.currency:
        raise ValidationFailedError("Currency mismatch between card and bank account")

    # Re-fetch the funding account with a row lock before touching balances.
    locked_result = await session.exec(
        select(BankAccount).where(BankAccount.id == bank_account.id).with_for_update()
    )
    bank_account = locked_result.first()
    if not bank_account:
        raise NotFoundError("Virtual card or bank account not found")

    if bank_account.account_status != AccountStatusEnum.Active:
        raise AccountNotActiveError("Bank account is not active")

    if bank_account.balance < amount:
        raise InsufficientBalanceError("Insufficient balance in bank account")

    reference = f"TOPUP{uuid.uuid4().hex[:8].upper()}"

    balance_before = bank_account.balance
    balance_after = balance_before - amount

    current_time = datetime.now(UTC)

    transaction = Transaction(
        amount=amount,
        description=description,
        reference=reference,
        transaction_type=TransactionTypeEnum.Transfer,
        transaction_category=TransactionCategoryEnum.Debit,
        status=TransactionStatusEnum.Completed,
        balance_before=balance_before,
        balance_after=balance_after,
        sender_account_id=bank_account.id,
        sender_id=bank_account.user_id,
        completed_at=current_time,
        transaction_metadata={
            "top_up_type": "virtual_card",
            "card_id": str(card.id),
            "card_last_four": card.last_four_digits,
            "currency": card.currency.value,
        },
    )

    bank_account.balance = balance_after
    card.available_balance = card.available_balance + amount
    card.total_topped_up = card.total_topped_up + amount

    card.last_top_up_date = current_time

    session.add(transaction)
    session.add(bank_account)
    session.add(card)
    await session.commit()

    await session.refresh(transaction)
    await session.refresh(card)

    return card, transaction


async def activate_virtual_card(
    card_id: UUID, activated_by: UUID, session: AsyncSession
) -> tuple[VirtualCard, User, str]:
    """Activate a pending card (account executives only); returns the raw CVV
    exactly once — only its hash is persisted."""
    statement = (
        select(VirtualCard, BankAccount, User)
        .select_from(VirtualCard)
        .join(BankAccount)
        .join(User)
        .where(VirtualCard.id == card_id)
    )

    result = await session.exec(statement)
    card_data = result.first()

    if not card_data:
        raise NotFoundError("Virtual card not found")

    card, bank_account, card_owner = card_data

    executive = await session.get(User, activated_by)

    if not executive or executive.role != RoleChoicesSchema.ACCOUNT_EXECUTIVE:
        raise ForbiddenError("Only account executives can activate virtual cards")

    if card.card_status == VirtualCardStatusEnum.Active:
        raise ValidationFailedError("Card is already active")

    new_cvv, cvv_hash = generate_cvv()

    card.card_status = VirtualCardStatusEnum.Active
    card.cvv_hash = cvv_hash

    if not card.card_metadata:
        card.card_metadata = {}

    card.card_metadata.update(
        {
            "activated_by": str(activated_by),
            "activated_at": datetime.now(UTC).isoformat(),
        }
    )

    session.add(card)
    await session.commit()

    await session.refresh(card)

    return card, card_owner, new_cvv


async def delete_virtual_card(
    card_id: UUID, user_id: UUID, session: AsyncSession
) -> dict:
    """Soft-delete a card (kept for audit) once its balance is zero."""
    statement = (
        select(VirtualCard, BankAccount)
        .join(BankAccount)
        .where(VirtualCard.id == card_id, BankAccount.user_id == user_id)
    )
    result = await session.exec(statement)
    card_account = result.first()

    if not card_account:
        raise NotFoundError("Virtual card not found or does not belong to the user")

    card, _ = card_account

    if card.physical_card_requested_at:
        raise ValidationFailedError("Cannot delete card with physical card request")

    if card.available_balance > 0:
        raise ValidationFailedError(
            "Cannot delete card with remaining balance",
            action="Please withdraw remaining balance first",
        )

    deletion_time = datetime.now(UTC)

    existing_metadata = card.card_metadata or {}

    new_metadata = {
        **existing_metadata,
        "deleted_at": deletion_time.isoformat(),
        "deletion_reason": "user_requested",
        "deleted_by": str(user_id),
        "card_status_before_deletion": card.card_status.value,
        "deletion_timestamp": deletion_time.timestamp(),
    }

    card.card_metadata = new_metadata

    card.card_status = VirtualCardStatusEnum.Inactive
    card.is_active = False

    session.add(card)
    await session.commit()
    await session.refresh(card)

    logger.info(
        f"Virtual card {card_id} soft deleted successfully",
    )
    return {
        "status": "success",
        "message": "Virtual card deleted successfully",
        "deleted_at": deletion_time,
    }
