"""Business logic for money movement: deposits, transfers, withdrawals,
statements, transaction history and fraud review.

Concurrency model
-----------------
Every operation that mutates an account balance re-reads the affected
``BankAccount`` rows with ``SELECT ... FOR UPDATE`` (:func:`_lock_account` /
:func:`_lock_accounts`) and re-validates status and balance *under the lock*
before writing, in a single commit. This removes the check-then-update race
that would otherwise allow overdrafts or lost deposits under concurrency.
When two accounts are involved they are always locked in ascending id order
so concurrent transfers cannot deadlock.

Fraud scoring runs *before* any balance mutation: the AI pipeline commits its
own bookkeeping (risk score rows, transaction metadata), which would release
row locks, so scoring never happens while a lock is held.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import any_, desc, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.models import User
from backend.app.auth.utils import generate_otp, verify_security_answer
from backend.app.bank_account.enums import AccountStatusEnum
from backend.app.bank_account.models import BankAccount
from backend.app.bank_account.utils import calculate_conversion
from backend.app.core.ai.enums import AIReviewStatusEnum
from backend.app.core.ai.models import TransactionRiskScore
from backend.app.core.ai.service import TransactionAIService
from backend.app.core.config import settings
from backend.app.core.exceptions import (
    AccountNotActiveError,
    FlaggedTransactionError,
    InsufficientBalanceError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)
from backend.app.core.logging import get_logger
from backend.app.core.services.transfer_alert import send_transfer_alert
from backend.app.core.services.withdrawal_alert import send_withdrawal_alert
from backend.app.core.tasks.statement import generate_statement_pdf
from backend.app.transaction.enums import (
    TransactionCategoryEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)
from backend.app.transaction.models import Transaction
from backend.app.transaction.utils import (
    TransactionFailureReason,
    mark_transaction_failed,
)

logger = get_logger()

_FLAGGED_TRANSACTION_MESSAGE = (
    "This transaction has been flagged as potentially fraudulent. An "
    "account executive will review the transaction, before its either "
    "approved or rejected"
)


async def _lock_account(
    session: AsyncSession, account_id: uuid.UUID
) -> BankAccount | None:
    """Fetch a bank account with a ``FOR UPDATE`` row lock."""
    result = await session.exec(
        select(BankAccount).where(BankAccount.id == account_id).with_for_update()
    )
    return result.first()


async def _lock_accounts(
    session: AsyncSession, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, BankAccount]:
    """Lock several accounts in ascending id order to avoid deadlocks."""
    accounts: dict[uuid.UUID, BankAccount] = {}
    for account_id in sorted(account_ids):
        account = await _lock_account(session, account_id)
        if account:
            accounts[account.id] = account
    return accounts


async def process_deposit(
    *,
    amount: Decimal,
    account_id: uuid.UUID,
    teller_id: uuid.UUID,
    description: str,
    session: AsyncSession,
) -> tuple[Transaction, BankAccount, User]:
    """Credit ``amount`` to an account on behalf of a teller.

    The account row is locked for the whole operation and everything is
    written in a single commit.
    """
    account = await _lock_account(session, account_id)

    if not account:
        raise NotFoundError("Account not found")

    account_owner = await session.get(User, account.user_id)
    if not account_owner:
        raise NotFoundError("Account not found")

    if account.account_status != AccountStatusEnum.Active:
        raise AccountNotActiveError("Account is not active")

    reference = f"DEP{uuid.uuid4().hex[:8].upper()}"

    balance_before = account.balance
    balance_after = balance_before + amount

    transaction = Transaction(
        amount=amount,
        description=description,
        reference=reference,
        transaction_type=TransactionTypeEnum.Deposit,
        transaction_category=TransactionCategoryEnum.Credit,
        status=TransactionStatusEnum.Pending,
        balance_before=balance_before,
        balance_after=balance_after,
        receiver_account_id=account_id,
        receiver_id=account_owner.id,
        processed_by=teller_id,
        transaction_metadata={
            "currency": account.currency,
            "account_number": account.account_number,
        },
    )
    teller = await session.get(User, teller_id)

    if teller:
        if transaction.transaction_metadata is None:
            transaction.transaction_metadata = {}
        transaction.transaction_metadata["teller_name"] = teller.full_name
        transaction.transaction_metadata["teller_email"] = teller.email

    account.balance = balance_after

    transaction.status = TransactionStatusEnum.Completed
    transaction.completed_at = datetime.now(UTC)

    session.add(transaction)
    session.add(account)
    await session.commit()

    await session.refresh(transaction)
    await session.refresh(account)

    return transaction, account, account_owner


async def initiate_transfer(
    *,
    sender_id: uuid.UUID,
    sender_account_id: uuid.UUID,
    receiver_account_number: str,
    amount: Decimal,
    description: str,
    security_answer: str,
    session: AsyncSession,
) -> tuple[Transaction, BankAccount, BankAccount, User, User]:
    """Create a pending transfer, run fraud scoring and issue an OTP.

    No balance is touched here: the debit/credit happens in
    :func:`complete_transfer` after OTP verification, under row locks.
    """
    own_account_result = await session.exec(
        select(BankAccount).where(
            BankAccount.account_number == receiver_account_number,
            BankAccount.user_id == sender_id,
        )
    )
    if own_account_result.first():
        raise ValidationFailedError(
            "Cannot transfer to your own account",
            action="Please use a different recipient account",
        )

    sender_stmt = (
        select(BankAccount, User)
        .join(User)
        .where(BankAccount.id == sender_account_id, BankAccount.user_id == sender_id)
    )
    sender_result = await session.exec(sender_stmt)
    sender_data = sender_result.first()

    if not sender_data:
        raise NotFoundError("Sender account not found")

    sender_account, sender = sender_data

    if sender_account.account_status != AccountStatusEnum.Active:
        raise AccountNotActiveError("Sender account is not active")

    if not sender.security_answer or not verify_security_answer(
        security_answer, sender.security_answer
    ):
        raise UnauthorizedError("Incorrect security answer")

    receiver_stmt = (
        select(BankAccount, User)
        .join(User)
        .where(BankAccount.account_number == receiver_account_number)
    )
    receiver_result = await session.exec(receiver_stmt)
    receiver_data = receiver_result.first()

    if not receiver_data:
        raise NotFoundError("Receiver account not found")

    receiver_account, receiver = receiver_data

    if receiver_account.account_status != AccountStatusEnum.Active:
        raise AccountNotActiveError("Receiver account is not active")

    if sender_account.balance < amount:
        raise InsufficientBalanceError("Insufficient balance")

    try:
        if sender_account.currency != receiver_account.currency:
            converted_amount, exchange_rate, conversion_fee = calculate_conversion(
                amount, sender_account.currency, receiver_account.currency
            )
        else:
            converted_amount = amount
            exchange_rate = Decimal("1.0")
            conversion_fee = Decimal("0")
    except Exception as e:
        raise ValidationFailedError(f"Currency conversion failed: {str(e)}") from e

    reference = f"TRF{uuid.uuid4().hex[:8].upper()}"

    transaction = Transaction(
        amount=amount,
        description=description,
        reference=reference,
        transaction_type=TransactionTypeEnum.Transfer,
        transaction_category=TransactionCategoryEnum.Debit,
        status=TransactionStatusEnum.Pending,
        balance_before=sender_account.balance,
        balance_after=sender_account.balance - amount,
        sender_account_id=sender_account.id,
        receiver_account_id=receiver_account.id,
        sender_id=sender.id,
        receiver_id=receiver.id,
        transaction_metadata={
            "conversion_rate": str(exchange_rate),
            "conversion_fee": str(conversion_fee),
            "original_amount": str(amount),
            "converted_amount": str(converted_amount),
            "from_currency": sender_account.currency.value,
            "to_currency": receiver_account.currency.value,
        },
    )
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)

    ai_service = TransactionAIService(session)
    risk_analysis = await ai_service.analyze_transaction(transaction, sender_id)

    if risk_analysis.get("needs_review", False):
        await ai_service.handle_flagged_transaction(transaction, risk_analysis)
        raise FlaggedTransactionError(
            _FLAGGED_TRANSACTION_MESSAGE,
            extra={
                "risk_analysis": {
                    "risk_score": risk_analysis["risk_score"],
                    "risk_factors": risk_analysis["risk_factors"],
                }
            },
        )

    otp = generate_otp()

    sender.otp = otp
    sender.otp_expiry_time = datetime.now(UTC) + timedelta(
        minutes=settings.OTP_EXPIRATION_MINUTES
    )

    session.add(transaction)
    session.add(sender)
    await session.commit()
    await session.refresh(transaction)

    return transaction, sender_account, receiver_account, sender, receiver


async def complete_transfer(
    *, reference: str, otp: str, session: AsyncSession
) -> tuple[Transaction, BankAccount, BankAccount, User, User]:
    """Apply a pending transfer after OTP verification.

    Both accounts are locked (in ascending id order) and every precondition is
    re-validated under the lock before balances change in a single commit.
    """
    stmt = select(Transaction).where(
        Transaction.reference == reference,
        Transaction.status == TransactionStatusEnum.Pending,
    )
    result = await session.exec(stmt)
    transaction = result.first()

    if not transaction:
        raise NotFoundError("Transfer not found")

    try:
        sender = await session.get(User, transaction.sender_id)
        receiver = await session.get(User, transaction.receiver_id)

        account_ids = [
            account_id
            for account_id in (
                transaction.sender_account_id,
                transaction.receiver_account_id,
            )
            if account_id is not None
        ]
        locked_accounts = await _lock_accounts(session, account_ids)
        sender_account = locked_accounts.get(transaction.sender_account_id)
        receiver_account = locked_accounts.get(transaction.receiver_account_id)

        if not all([sender_account, receiver_account, sender, receiver]):
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.INVALID_ACCOUNT,
                details={
                    "sender_account_found": bool(sender_account),
                    "receiver_account_found": bool(receiver_account),
                    "sender_found": bool(sender),
                    "receiver_found": bool(receiver),
                },
                session=session,
                error_message="Account information not found",
            )
            raise NotFoundError("Account information not found")

        assert sender is not None
        assert receiver is not None
        assert sender_account is not None
        assert receiver_account is not None

        if not sender.otp or sender.otp != otp:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.INVALID_OTP,
                details={"provided_otp": otp},
                session=session,
                error_message="Invalid OTP",
            )
            raise UnauthorizedError("Invalid OTP")

        if (
            not sender.otp_expiry_time
            or datetime.now(UTC) > sender.otp_expiry_time
        ):
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.OTP_EXPIRED,
                details={
                    "expiry_time": (
                        sender.otp_expiry_time.isoformat()
                        if sender.otp_expiry_time
                        else None
                    ),
                    "current_time": datetime.now(UTC).isoformat(),
                },
                session=session,
                error_message="OTP has expired",
            )
            raise UnauthorizedError("OTP has expired")

        if sender_account.account_status != AccountStatusEnum.Active:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.ACCOUNT_INACTIVE,
                details={"account": "sender"},
                session=session,
                error_message="Sender account is no longer active",
            )
            raise AccountNotActiveError("Sender account is no longer active")

        if receiver_account.account_status != AccountStatusEnum.Active:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.ACCOUNT_INACTIVE,
                details={"account": "receiver"},
                session=session,
                error_message="Receiver account is no longer active",
            )
            raise AccountNotActiveError("Receiver account is no longer active")

        if sender_account.balance < transaction.amount:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.INSUFFICIENT_BALANCE,
                details={
                    "required_amount": str(transaction.amount),
                    "available_balance": str(sender_account.balance),
                    "shortfall": str(transaction.amount - sender_account.balance),
                },
                session=session,
                error_message="Insufficient balance",
            )
            raise InsufficientBalanceError("Insufficient balance")

        if not transaction.transaction_metadata:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.SYSTEM_ERROR,
                details={"error": "Missing transaction metadata"},
                session=session,
                error_message="System error: Missing transaction metadata",
            )
            raise ValidationFailedError("System error: Missing transaction metadata")

        converted_amount = Decimal(transaction.transaction_metadata["converted_amount"])

        sender_account.balance = sender_account.balance - transaction.amount
        receiver_account.balance = receiver_account.balance + converted_amount

        transaction.status = TransactionStatusEnum.Completed
        transaction.completed_at = datetime.now(UTC)

        sender.otp = ""
        sender.otp_expiry_time = None

        session.add(transaction)
        session.add(sender_account)
        session.add(receiver_account)
        session.add(sender)
        await session.commit()

        await session.refresh(transaction)
        await session.refresh(sender_account)
        await session.refresh(receiver_account)
        await session.refresh(sender)
        await session.refresh(receiver)

        return transaction, sender_account, receiver_account, sender, receiver

    except (
        NotFoundError,
        UnauthorizedError,
        AccountNotActiveError,
        InsufficientBalanceError,
        ValidationFailedError,
    ):
        raise
    except Exception as e:
        await session.rollback()
        await mark_transaction_failed(
            transaction=transaction,
            reason=TransactionFailureReason.SYSTEM_ERROR,
            details={"error": str(e)},
            session=session,
            error_message="A system error occurred",
        )
        logger.error(f"Failed to complete transfer: {e}")
        raise


async def process_withdrawal(
    *,
    account_number: str,
    amount: Decimal,
    username: str,
    description: str,
    session: AsyncSession,
) -> tuple[Transaction, BankAccount, User]:
    """Debit ``amount`` from an account after fraud scoring.

    Fraud scoring runs first (it commits its own records, which would release
    row locks); only a clean transaction proceeds to lock the account,
    re-validate the balance under the lock and apply the debit atomically.
    """
    statement = (
        select(BankAccount, User)
        .join(User)
        .where(BankAccount.account_number == account_number, User.username == username)
    )
    result = await session.exec(statement)
    account_user = result.first()

    if not account_user:
        raise NotFoundError("Account or username not found")

    account, user = account_user

    if account.account_status != AccountStatusEnum.Active:
        raise AccountNotActiveError("Account is not active")

    if account.balance < amount:
        raise InsufficientBalanceError("Insufficient balance")

    reference = f"WTH{uuid.uuid4().hex[:8].upper()}"

    transaction = Transaction(
        amount=amount,
        description=description,
        reference=reference,
        transaction_type=TransactionTypeEnum.Withdrawal,
        transaction_category=TransactionCategoryEnum.Debit,
        status=TransactionStatusEnum.Pending,
        balance_before=account.balance,
        balance_after=account.balance - amount,
        sender_account_id=account.id,
        sender_id=user.id,
        transaction_metadata={
            "currency": account.currency.value,
            "account_number": account.account_number,
            "withdrawal_method": "cash",
        },
    )

    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)

    ai_service = TransactionAIService(session)
    risk_analysis = await ai_service.analyze_transaction(transaction, user.id)

    if risk_analysis.get("needs_review", False):
        # The balance has NOT been touched yet, so flagging leaves no
        # inconsistent state: the transaction is marked failed/for review
        # and the money stays in the account until a human decides.
        await ai_service.handle_flagged_transaction(transaction, risk_analysis)
        raise FlaggedTransactionError(
            _FLAGGED_TRANSACTION_MESSAGE,
            extra={
                "risk_analysis": {
                    "risk_score": risk_analysis["risk_score"],
                    "risk_factors": risk_analysis["risk_factors"],
                }
            },
        )

    locked_account = await _lock_account(session, account.id)
    if not locked_account:
        raise NotFoundError("Account or username not found")
    account = locked_account

    if account.account_status != AccountStatusEnum.Active:
        await mark_transaction_failed(
            transaction=transaction,
            reason=TransactionFailureReason.ACCOUNT_INACTIVE,
            details={"account": "sender"},
            session=session,
            error_message="Account is not active",
        )
        raise AccountNotActiveError("Account is not active")

    if account.balance < amount:
        await mark_transaction_failed(
            transaction=transaction,
            reason=TransactionFailureReason.INSUFFICIENT_BALANCE,
            details={
                "required_amount": str(amount),
                "available_balance": str(account.balance),
            },
            session=session,
            error_message="Insufficient balance",
        )
        raise InsufficientBalanceError("Insufficient balance")

    balance_before = account.balance
    balance_after = balance_before - amount

    transaction.balance_before = balance_before
    transaction.balance_after = balance_after
    transaction.status = TransactionStatusEnum.Completed
    transaction.completed_at = datetime.now(UTC)

    account.balance = balance_after

    session.add(transaction)
    session.add(account)
    await session.commit()

    await session.refresh(transaction)
    await session.refresh(account)

    return transaction, account, user


async def get_user_transactions(
    user_id: uuid.UUID,
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    transaction_type: TransactionTypeEnum | None = None,
    transaction_category: TransactionCategoryEnum | None = None,
    transaction_status: TransactionStatusEnum | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
) -> tuple[list[Transaction], int]:
    """Paginated, filterable transaction history for a user.

    Counterparty relationships are eager-loaded with ``selectinload`` in the
    main query (fixed N+1: previously each row triggered a separate refresh).
    """
    account_stmt = select(BankAccount.id).where(BankAccount.user_id == user_id)
    result = await session.exec(account_stmt)
    account_ids = list(result.all())

    if not account_ids:
        return [], 0

    base_query = select(Transaction).where(
        or_(
            Transaction.sender_id == user_id,
            Transaction.receiver_id == user_id,
            Transaction.sender_account_id == any_(account_ids),
            Transaction.receiver_account_id == any_(account_ids),
        )
    )
    if start_date:
        base_query = base_query.where(Transaction.created_at >= start_date)

    if end_date:
        base_query = base_query.where(Transaction.created_at <= end_date)

    if transaction_type:
        base_query = base_query.where(Transaction.transaction_type == transaction_type)

    if transaction_category:
        base_query = base_query.where(
            Transaction.transaction_category == transaction_category
        )
    if transaction_status:
        base_query = base_query.where(Transaction.status == transaction_status)

    if min_amount is not None:
        base_query = base_query.where(Transaction.amount >= min_amount)
    if max_amount is not None:
        base_query = base_query.where(Transaction.amount <= max_amount)

    base_query = base_query.order_by(desc(Transaction.created_at))

    count_query = select(func.count()).select_from(base_query.subquery())
    total = await session.exec(count_query)
    total_count = total.first() or 0

    page_query = (
        base_query.offset(skip)
        .limit(limit)
        .options(
            selectinload(Transaction.sender),
            selectinload(Transaction.receiver),
            selectinload(Transaction.sender_account),
            selectinload(Transaction.receiver_account),
        )
    )
    transactions = await session.exec(page_query)
    transaction_list = list(transactions.all())

    for transaction in transaction_list:
        if not transaction.transaction_metadata:
            transaction.transaction_metadata = {}

        if transaction.sender_id == user_id:
            if transaction.receiver:
                transaction.transaction_metadata["counterparty_name"] = (
                    transaction.receiver.full_name
                )
            if transaction.receiver_account:
                transaction.transaction_metadata["counterparty_account"] = (
                    transaction.receiver_account.account_number
                )
        else:
            if transaction.sender:
                transaction.transaction_metadata["counterparty_name"] = (
                    transaction.sender.full_name
                )
            if transaction.sender_account:
                transaction.transaction_metadata["counterparty_account"] = (
                    transaction.sender_account.account_number
                )

    return transaction_list, total_count


async def get_user_statement_data(
    user_id: uuid.UUID,
    start_date: datetime,
    end_date: datetime,
    session: AsyncSession,
) -> tuple[dict[str, Any], list[Transaction]]:
    """Basic user info plus their transactions within a date range."""
    user_stmt = select(User).where(User.id == user_id)
    result = await session.exec(user_stmt)
    user = result.first()

    if not user:
        raise ValueError(f"User {user_id} not found")

    middle = f"{user.middle_name} " if user.middle_name else ""
    full_name = f"{user.first_name} {middle}{user.last_name}".title().strip()

    user_info = {
        "username": user.username,
        "email": user.email,
        "full_name": full_name,
    }

    txn_stmt = (
        select(Transaction)
        .where(
            (Transaction.sender_id == user_id) | (Transaction.receiver_id == user_id),
            Transaction.created_at >= start_date,
            Transaction.created_at <= end_date,
        )
        .order_by(desc(Transaction.created_at))
    )

    txn_result = await session.exec(txn_stmt)
    transactions = txn_result.all()

    return user_info, list(transactions)


async def prepare_statement_data(
    user_id: uuid.UUID,
    start_date: datetime,
    end_date: datetime,
    session: AsyncSession,
    account_number: str | None = None,
) -> dict:
    """Collect the data the Celery task needs to render a PDF statement.

    Account relationships are eager-loaded (fixed N+1: previously each
    transaction issued two extra ``session.get`` calls inside the loop).
    """
    user_query = select(User).where(User.id == user_id)
    result = await session.exec(user_query)
    user = result.first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    if account_number:
        account_query = select(BankAccount).where(
            BankAccount.account_number == account_number,
            BankAccount.user_id == user_id,
        )
        account_result = await session.exec(account_query)
        account = account_result.first()

        if not account:
            raise ValueError("Account not found or does not belong to user")

        accounts = [account]
    else:
        accounts_query = select(BankAccount).where(BankAccount.user_id == user_id)
        accounts_result = await session.exec(accounts_query)
        accounts = list(accounts_result.all())

    account_details = []

    for acc in accounts:
        if acc.account_number:
            account_details.append(
                {
                    "account_number": acc.account_number,
                    "account_name": acc.account_name,
                    "account_type": acc.account_type.value,
                    "currency": acc.currency.value,
                    "balance": str(acc.balance),
                }
            )
    account_ids = [acc.id for acc in accounts]

    transactions_query = (
        select(Transaction)
        .where(
            or_(
                Transaction.sender_account_id == any_(account_ids),
                Transaction.receiver_account_id == any_(account_ids),
            ),
            Transaction.created_at >= start_date,
            Transaction.created_at <= end_date,
            Transaction.status == TransactionStatusEnum.Completed,
        )
        .order_by(desc(Transaction.created_at))
        .options(
            selectinload(Transaction.sender_account),
            selectinload(Transaction.receiver_account),
        )
    )

    result = await session.exec(transactions_query)
    transactions = result.all()

    user_data = {
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": (
            f"{user.first_name} "
            f"{user.middle_name + ' ' if user.middle_name else ''}"
            f"{user.last_name}"
        ).strip(),
        "accounts": account_details,
    }

    transaction_data = []
    for txn in transactions:
        transaction_data.append(
            {
                "reference": txn.reference,
                "amount": str(txn.amount),
                "description": txn.description,
                "created_at": txn.created_at.strftime("%Y-%m-%d"),
                "transaction_type": txn.transaction_type.value,
                "transaction_category": txn.transaction_category.value,
                "balance_after": str(txn.balance_after),
                "sender_account": (
                    txn.sender_account.account_number if txn.sender_account else None
                ),
                "receiver_account": (
                    txn.receiver_account.account_number
                    if txn.receiver_account
                    else None
                ),
                "metadata": txn.transaction_metadata,
            }
        )
    return {
        "user": user_data,
        "transactions": transaction_data,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "is_single_account": bool(account_number),
    }


async def generate_user_statement(
    user_id: uuid.UUID,
    start_date: datetime,
    end_date: datetime,
    session: AsyncSession,
    account_number: str | None = None,
) -> dict:
    """Queue asynchronous PDF statement generation via Celery."""
    try:
        statement_data = await prepare_statement_data(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            session=session,
            account_number=account_number,
        )
    except ValueError as e:
        raise ValidationFailedError(str(e)) from e

    statement_id = str(uuid.uuid4())

    task = generate_statement_pdf.delay(
        statement_data=statement_data, statement_id=statement_id
    )

    return {
        "status": "pending",
        "message": "Statement generation initiated",
        "statement_id": statement_id,
        "task_id": task.id,
    }


async def review_flagged_transaction(
    transaction_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    is_fraud: bool,
    approve_transaction: bool,
    notes: str | None,
    session: AsyncSession,
) -> dict:
    """Record a human fraud-review decision, optionally completing the
    original transfer/withdrawal when it is approved."""
    query = (
        select(Transaction, TransactionRiskScore)
        .join(TransactionRiskScore)
        .where(Transaction.id == transaction_id)
    )

    result = await session.exec(query)
    transaction_data = result.first()

    if not transaction_data:
        raise NotFoundError("Transaction not found")

    transaction, risk_score = transaction_data

    if transaction.ai_review_status != AIReviewStatusEnum.FLAGGED:
        raise ValidationFailedError(
            "Transaction is not flagged for review",
            extra={"current_status": transaction.ai_review_status},
        )

    if is_fraud:
        transaction.ai_review_status = AIReviewStatusEnum.CONFIRMED_FRAUD
        risk_score.is_confirmed_fraud = True
        risk_score.reviewed_by = reviewer_id
        transaction.status = TransactionStatusEnum.Failed
    else:
        transaction.ai_review_status = AIReviewStatusEnum.CLEARED

    if approve_transaction:
        if transaction.transaction_type == TransactionTypeEnum.Transfer:
            await _complete_approved_transfer(transaction, session)
        elif transaction.transaction_type == TransactionTypeEnum.Withdrawal:
            await _complete_approved_withdrawal(transaction, session)

    if not transaction.transaction_metadata:
        transaction.transaction_metadata = {}

    transaction.transaction_metadata["fraud_review"] = {
        "reviewed_at": datetime.now(UTC).isoformat(),
        "reviewed_by": str(reviewer_id),
        "is_fraud": is_fraud,
        "notes": notes,
    }

    session.add(transaction)
    session.add(risk_score)
    await session.commit()

    return {
        "status": "success",
        "message": "Transaction reviewed successfully",
        "transaction_id": str(transaction_id),
        "is_fraud": is_fraud,
        "review_status": transaction.ai_review_status,
        "risk_score": risk_score.risk_score,
    }


async def _complete_approved_transfer(transaction: Transaction, session: AsyncSession):
    """Apply the balance movement of a transfer approved after fraud review.

    Uses the same ordered row-locking discipline as :func:`complete_transfer`.
    """
    try:
        sender = await session.get(User, transaction.sender_id)
        receiver = await session.get(User, transaction.receiver_id)

        account_ids = [
            account_id
            for account_id in (
                transaction.sender_account_id,
                transaction.receiver_account_id,
            )
            if account_id is not None
        ]
        locked_accounts = await _lock_accounts(session, account_ids)
        sender_account = locked_accounts.get(transaction.sender_account_id)
        receiver_account = locked_accounts.get(transaction.receiver_account_id)

        if not sender:
            raise ValueError("Sender not found")
        if not receiver:
            raise ValueError("Receiver not found")
        if not sender_account:
            raise ValueError("Sender account not found")
        if not receiver_account:
            raise ValueError("Receiver account not found")

        if not transaction.transaction_metadata:
            raise ValueError("Transaction metadata is missing")

        converted_amount_str = transaction.transaction_metadata.get("converted_amount")

        if not converted_amount_str:
            raise ValueError("Converted amount is missing from metadata")

        try:
            converted_amount = Decimal(converted_amount_str)
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid converted amount format:{converted_amount_str}"
            ) from None

        if sender_account.balance < transaction.amount:
            raise ValueError("Insufficient balance for transfer")

        try:
            sender_account.balance = sender_account.balance - transaction.amount
            receiver_account.balance = receiver_account.balance + converted_amount

            transaction.status = TransactionStatusEnum.Completed
            transaction.completed_at = datetime.now(UTC)

            session.add(sender_account)
            session.add(receiver_account)
            session.add(transaction)

            await session.commit()

            await session.refresh(transaction)
            await session.refresh(sender_account)
            await session.refresh(receiver_account)

            try:
                await send_transfer_alert(
                    sender_email=sender.email,
                    receiver_email=receiver.email,
                    sender_name=sender.full_name,
                    receiver_name=receiver.full_name,
                    sender_account_number=sender_account.account_number or "Unknown",
                    receiver_account_number=receiver_account.account_number
                    or "Unknown",
                    amount=transaction.amount,
                    converted_amount=converted_amount,
                    sender_currency=sender_account.currency,
                    receiver_currency=receiver_account.currency,
                    exchange_rate=Decimal(
                        transaction.transaction_metadata.get("conversion_rate", "1"),
                    ),
                    conversion_fee=Decimal(
                        transaction.transaction_metadata.get("conversion_fee", "0"),
                    ),
                    description=transaction.description,
                    reference=transaction.reference,
                    transaction_date=transaction.completed_at or transaction.created_at,
                    sender_balance=sender_account.balance,
                    receiver_balance=receiver_account.balance,
                )
                logger.info(
                    "Successfully sent transfer approval notification "
                    f"for transaction {transaction.reference}"
                )
            except Exception as e:
                logger.error(f"Failed to send transfer approval notification: {e}")
        except Exception as e:
            await session.rollback()
            raise ValueError(f"Failed to process transfer: {str(e)}") from e

    except ValueError as e:
        await session.rollback()
        logger.error(f"Validation error in _complete_approved_transfer: {e}")

        transaction.status = TransactionStatusEnum.Failed
        transaction.transaction_metadata = {
            **(transaction.transaction_metadata or {}),
            "failure_reason": str(e),
            "failed_at": datetime.now(UTC).isoformat(),
        }
        session.add(transaction)
        await session.commit()
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Unexpected error in _complete_approved_transfer: {e}")
        raise


async def _complete_approved_withdrawal(
    transaction: Transaction, session: AsyncSession
):
    """Apply the balance movement of a withdrawal approved after fraud review."""
    try:
        user = await session.get(User, transaction.sender_id)
        account = (
            await _lock_account(session, transaction.sender_account_id)
            if transaction.sender_account_id
            else None
        )

        if not user:
            raise ValueError("User not found")
        if not account:
            raise ValueError("Account not found")

        if account.balance < transaction.amount:
            raise ValueError("Insufficient balance for withdrawal")
        try:
            account.balance = account.balance - transaction.amount

            transaction.status = TransactionStatusEnum.Completed
            transaction.completed_at = datetime.now(UTC)

            session.add(account)
            session.add(transaction)

            await session.commit()

            await session.refresh(transaction)
            await session.refresh(account)

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
                logger.info(
                    "Successfully sent withdrawal approval notification "
                    f"for transaction {transaction.reference}"
                )
            except Exception as e:
                logger.error(f"Failed to send withdrawal approval notification: {e}")
        except Exception as e:
            await session.rollback()
            raise ValueError(f"Failed to process withdrawal: {str(e)}") from e

    except ValueError as e:
        await session.rollback()
        logger.error(f"Validation error in _complete_approved_withdrawal: {e}")

        transaction.status = TransactionStatusEnum.Failed
        transaction.transaction_metadata = {
            **(transaction.transaction_metadata or {}),
            "failure_reason": str(e),
            "failed_at": datetime.now(UTC).isoformat(),
        }
        session.add(transaction)
        await session.commit()
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Unexpected error in _complete_approved_withdrawal: {e}")
        raise


async def get_user_risk_history(
    user_id: uuid.UUID,
    session: AsyncSession,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_risk_score: float | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[dict], int]:
    """Paginated fraud-risk score history for a user's transactions."""
    base_query = (
        select(Transaction, TransactionRiskScore)
        .join(TransactionRiskScore)
        .where(Transaction.sender_id == user_id)
    )

    if start_date:
        base_query = base_query.where(Transaction.created_at >= start_date)

    if end_date:
        base_query = base_query.where(Transaction.created_at <= end_date)

    if min_risk_score is not None:
        base_query = base_query.where(TransactionRiskScore.risk_score >= min_risk_score)

    base_query = base_query.order_by(
        desc(Transaction.created_at), desc(TransactionRiskScore.risk_score)
    )

    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.exec(count_query)
    total_count = total_result.first() or 0

    paginated_query = base_query.offset(skip).limit(limit)

    result = await session.exec(paginated_query)
    transactions = result.all()

    history = []

    for transaction, risk_score in transactions:
        history.append(
            {
                "transaction_id": str(transaction.id),
                "reference": transaction.reference,
                "amount": str(transaction.amount),
                "created_at": transaction.created_at,
                "risk_score": risk_score.risk_score,
                "risk_factors": risk_score.risk_factors,
                "review_status": transaction.ai_review_status,
                "is_confirmed_fraud": risk_score.is_confirmed_fraud,
                "reviewed_by": (
                    str(risk_score.reviewed_by) if risk_score.reviewed_by else None
                ),
                "review_details": (
                    transaction.transaction_metadata.get("fraud_review")
                    if transaction.transaction_metadata
                    else None
                ),
            }
        )
    return history, total_count
