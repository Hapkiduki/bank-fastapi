"""Business logic for the bank account lifecycle (creation, KYC activation)."""

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.models import User
from backend.app.bank_account.enums import AccountStatusEnum
from backend.app.bank_account.models import BankAccount
from backend.app.bank_account.schema import BankAccountCreateSchema
from backend.app.bank_account.utils import generate_account_number
from backend.app.core.config import settings
from backend.app.core.exceptions import NotFoundError, ValidationFailedError
from backend.app.core.logging import get_logger

logger = get_logger()


async def get_primary_bank_account(
    user_id: UUID, session: AsyncSession
) -> BankAccount | None:
    """Return the user's primary account, if any."""
    statement = select(BankAccount).where(
        BankAccount.user_id == user_id, BankAccount.is_primary
    )
    result = await session.exec(statement)
    return result.first()


async def validate_user_kyc(user: User) -> bool:
    """KYC gate: the user needs a profile and at least one next of kin."""
    if not user.profile:
        return False
    if not user.next_of_kins or len(user.next_of_kins) == 0:
        return False
    return True


async def create_bank_account(
    user_id: UUID, account_data: BankAccountCreateSchema, session: AsyncSession
) -> BankAccount:
    """Open a new (pending) bank account for a KYC-complete user.

    Enforces the per-user account cap and the single-primary-account rule.
    """
    statement = select(User).where(User.id == user_id)
    result = await session.exec(statement)
    user = result.first()

    if not user:
        raise NotFoundError("User not found")

    await session.refresh(user, ["profile", "next_of_kins"])

    if not await validate_user_kyc(user):
        raise ValidationFailedError(
            "KYC requirements not met",
            action="Please complete your profile and add at least one next of kin",
        )

    statement = select(BankAccount).where(BankAccount.user_id == user_id)
    result = await session.exec(statement)
    existing_accounts = result.all()
    if len(existing_accounts) >= settings.MAX_BANK_ACCOUNTS:
        raise ValidationFailedError("Maximum number of accounts reached")

    if account_data.is_primary:
        primary_exists = any(account.is_primary for account in existing_accounts)

        if primary_exists:
            raise ValidationFailedError(
                "A primary account already exists",
                action="Please unset the existing primary account first",
            )
    elif len(existing_accounts) == 0:
        account_data.is_primary = True

    account_number = generate_account_number(account_data.currency)
    new_account = BankAccount(
        **account_data.model_dump(exclude={"account_number"}),
        user_id=user_id,
        account_number=account_number,
    )

    session.add(new_account)

    await session.commit()
    await session.refresh(new_account)

    return new_account


async def activate_bank_account(
    account_id: UUID,
    verified_by: UUID,
    session: AsyncSession,
) -> tuple[BankAccount, User]:
    """Mark an account KYC-verified and active (a user cannot verify their own)."""
    statement = (
        select(BankAccount, User)
        .join(User)
        .where(BankAccount.id == account_id, BankAccount.user_id != verified_by)
    )
    result = await session.exec(statement)
    account_user_tuple = result.first()

    if not account_user_tuple:
        raise NotFoundError("Bank account not found")

    account, user = account_user_tuple

    if account.account_status == AccountStatusEnum.Active:
        raise ValidationFailedError("Account is already activated")

    account.kyc_submitted = True
    account.kyc_verified = True
    account.kyc_verified_on = datetime.now(UTC)
    account.kyc_verified_by = verified_by
    account.account_status = AccountStatusEnum.Active

    session.add(account)
    await session.commit()
    await session.refresh(account)

    return account, user
