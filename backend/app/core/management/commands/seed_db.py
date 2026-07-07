#!/usr/bin/env python
"""
Database seed script for populating the database with test data.
This will create users, profiles, bank accounts, and transactions
to provide sufficient data for testing ML endpoints.
"""

import argparse
import asyncio
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# SQLModel imports
from sqlmodel.ext.asyncio.session import AsyncSession

# Import your models and enums
from backend.app.auth.models import User
from backend.app.auth.schema import (
    AccountStatusSchema,
    RoleChoicesSchema,
    SecurityQuestionsSchema,
)
from backend.app.auth.utils import generate_password_hash, hash_security_answer
from backend.app.bank_account.enums import (
    AccountCurrencyEnum,
    AccountStatusEnum,
    AccountTypeEnum,
)
from backend.app.bank_account.models import BankAccount
from backend.app.bank_account.utils import generate_account_number
from backend.app.core.ai.enums import AIReviewStatusEnum
from backend.app.core.ai.models import TransactionRiskScore

# Import database session factory
from backend.app.core.db import async_session, init_db
from backend.app.next_of_kin.enums import RelationshipTypeEnum
from backend.app.next_of_kin.models import NextOfKin
from backend.app.transaction.enums import (
    TransactionCategoryEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)
from backend.app.transaction.models import Transaction
from backend.app.user_profile.enums import (
    EmploymentStatusEnum,
    GenderEnum,
    IdentificationTypeEnum,
    MaritalStatusEnum,
    SalutationEnum,
)
from backend.app.user_profile.models import Profile

# Import the correct types
from backend.app.user_profile.schema import CountryShortName, PhoneNumber

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
NUM_USERS = 20
NUM_TRANSACTIONS_PER_USER = 50
NUM_FRAUD_TRANSACTIONS = 10  # Number of transactions to mark as fraudulent
TRANSACTION_DATE_RANGE = 90  # Days to spread transactions over

# Sample data
FIRST_NAMES = [
    "John",
    "Jane",
    "Alice",
    "Bob",
    "Charlie",
    "Diana",
    "Edward",
    "Fiona",
    "George",
    "Hannah",
    "Ian",
    "Julia",
    "Kevin",
    "Laura",
    "Michael",
    "Natalie",
    "Oliver",
    "Penelope",
    "Quentin",
    "Rachel",
]

LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Jones",
    "Brown",
    "Davis",
    "Miller",
    "Wilson",
    "Moore",
    "Taylor",
    "Anderson",
    "Thomas",
    "Jackson",
    "White",
    "Harris",
    "Martin",
    "Thompson",
    "Garcia",
    "Martinez",
    "Robinson",
]

CITIES = [
    "New York",
    "Los Angeles",
    "Chicago",
    "Houston",
    "Phoenix",
    "Philadelphia",
    "San Antonio",
    "San Diego",
    "Dallas",
    "San Jose",
    "Austin",
    "Jacksonville",
    "Fort Worth",
    "Columbus",
    "San Francisco",
    "Charlotte",
    "Indianapolis",
    "Seattle",
    "Denver",
    "Washington",
]

COUNTRIES = ["US", "GB", "CA", "AU", "DE", "FR", "JP", "CN", "BR", "IN"]

EMPLOYERS = [
    "Tech Corp",
    "Finance Inc.",
    "Healthcare Ltd.",
    "Education Systems",
    "Retail Group",
    "Manufacturing Co.",
    "Energy Ltd.",
    "Construction Inc.",
    "Hospitality Group",
    "Media Corp",
]

TRANSACTION_DESCRIPTIONS = [
    "Salary payment",
    "Grocery shopping",
    "Utility bill",
    "Rent payment",
    "Online purchase",
    "Subscription fee",
    "Restaurant bill",
    "Travel expense",
    "Medical payment",
    "Insurance premium",
    "Investment deposit",
    "Loan repayment",
    "Education fee",
    "Entertainment",
    "Gift transfer",
    "Charity donation",
    "Tax payment",
    "Refund received",
    "Service fee",
    "Maintenance cost",
]


async def create_users_with_profiles(session: AsyncSession, num_users: int):
    """Create users with profiles and return them"""
    users = []
    admin_user = None
    account_executive_user = None
    teller_user = None

    for i in range(num_users):
        # Create a user
        user_id = uuid.uuid4()
        username = f"user{i+1}"
        email = f"user{i+1}@example.com"
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        middle_name = random.choice(FIRST_NAMES) if random.random() > 0.7 else None
        id_no = random.randint(10000000, 99999999)

        # Assign roles - first user is admin, second is account executive, third is teller
        if i == 0:
            role = RoleChoicesSchema.SUPER_ADMIN
        elif i == 1:
            role = RoleChoicesSchema.ACCOUNT_EXECUTIVE
        elif i == 2:
            role = RoleChoicesSchema.TELLER
        else:
            role = RoleChoicesSchema.CUSTOMER

        # Create a User object
        user = User(
            id=user_id,
            username=username,
            email=email,
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
            id_no=id_no,
            hashed_password=generate_password_hash("password123"),
            is_active=True,
            account_status=AccountStatusSchema.ACTIVE,
            security_question=random.choice(list(SecurityQuestionsSchema)),
            security_answer=hash_security_answer("test answer"),
            role=role,
        )

        # Remember special users
        if role == RoleChoicesSchema.SUPER_ADMIN:
            admin_user = user
        elif role == RoleChoicesSchema.ACCOUNT_EXECUTIVE:
            account_executive_user = user
        elif role == RoleChoicesSchema.TELLER:
            teller_user = user

        # Create a profile for the user
        profile = Profile(
            id=uuid.uuid4(),
            user_id=user_id,
            title=random.choice(list(SalutationEnum)),
            gender=random.choice(list(GenderEnum)),
            date_of_birth=datetime.now(UTC)
            - timedelta(days=random.randint(8000, 25000)),
            country_of_birth=CountryShortName(random.choice(COUNTRIES)),
            place_of_birth=random.choice(CITIES),
            marital_status=random.choice(list(MaritalStatusEnum)),
            means_of_identification=random.choice(list(IdentificationTypeEnum)),
            id_issue_date=datetime.now(UTC)
            - timedelta(days=random.randint(100, 1000)),
            id_expiry_date=datetime.now(UTC)
            + timedelta(days=random.randint(100, 1000)),
            passport_number=f"P{random.randint(10000000, 99999999)}",
            nationality=CountryShortName(random.choice(COUNTRIES)),
            phone_number=PhoneNumber(f"+1{random.randint(1000000000, 9999999999)}"),
            address=f"{random.randint(1, 999)} Main St",
            city=random.choice(CITIES),
            country=CountryShortName(random.choice(COUNTRIES)),
            employment_status=random.choice(list(EmploymentStatusEnum)),
            employer_name=random.choice(EMPLOYERS),
            employer_address=f"{random.randint(1, 999)} Business Ave",
            employer_city=random.choice(CITIES),
            employer_country=CountryShortName(random.choice(COUNTRIES)),
            annual_income=float(random.randint(30000, 150000)),
            date_of_employment=datetime.now(UTC)
            - timedelta(days=random.randint(100, 3000)),
        )

        # Create next of kin
        next_of_kin = NextOfKin(
            id=uuid.uuid4(),
            user_id=user_id,
            full_name=f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
            relationship=random.choice(list(RelationshipTypeEnum)),
            email=f"kin{i+1}@example.com",
            phone_number=PhoneNumber(f"+1{random.randint(1000000000, 9999999999)}"),
            address=f"{random.randint(1, 999)} Kin St",
            city=random.choice(CITIES),
            country=CountryShortName(random.choice(COUNTRIES)),
            nationality=CountryShortName(random.choice(COUNTRIES)),
            is_primary=True,
        )

        # Add all objects to the session
        session.add(user)
        session.add(profile)
        session.add(next_of_kin)

        users.append(user)

    # Commit to the database
    await session.commit()

    # Refresh all users to get their latest data
    for user in users:
        await session.refresh(user)

    return users, admin_user, account_executive_user, teller_user


async def create_bank_accounts(session: AsyncSession, users):
    """Create bank accounts for users"""
    accounts = []

    for user in users:
        # Each user gets 1-2 bank accounts
        num_accounts = random.randint(1, 2)

        for j in range(num_accounts):
            account_currency = random.choice(list(AccountCurrencyEnum))
            account_number = generate_account_number(account_currency)

            account = BankAccount(
                id=uuid.uuid4(),
                user_id=user.id,
                account_type=AccountTypeEnum.Savings,
                currency=account_currency,
                account_status=AccountStatusEnum.Active,
                account_number=account_number,
                account_name=f"{user.first_name} {user.last_name}",
                balance=Decimal(random.randint(1000, 50000)),
                is_primary=j == 0,  # First account is primary
                kyc_submitted=True,
                kyc_verified=True,
                kyc_verified_on=datetime.now(UTC)
                - timedelta(days=random.randint(1, 30)),
            )

            session.add(account)
            accounts.append(account)

    # Commit to the database
    await session.commit()

    # Refresh all accounts
    for account in accounts:
        await session.refresh(account)

    return accounts


async def create_transactions(
    session: AsyncSession,
    accounts,
    users,
    date_range_days,
    num_transactions_per_user,
    num_fraud_transactions,
):
    """Create transactions between accounts"""
    transactions = []
    all_user_accounts = {}

    # Group accounts by user
    for account in accounts:
        if account.user_id not in all_user_accounts:
            all_user_accounts[account.user_id] = []
        all_user_accounts[account.user_id].append(account)

    # Get account executive for approval
    account_executive = None
    for user in users:
        if user.role == RoleChoicesSchema.ACCOUNT_EXECUTIVE:
            account_executive = user
            break

    teller = None
    for user in users:
        if user.role == RoleChoicesSchema.TELLER:
            teller = user
            break

    # Create transactions
    today = datetime.now(UTC)
    start_date = today - timedelta(days=date_range_days)

    for user_id, user_accounts in all_user_accounts.items():
        for _ in range(num_transactions_per_user):
            # Skip if user has no accounts
            if not user_accounts:
                continue

            # Randomly select a sender account
            sender_account = random.choice(user_accounts)

            # Determine transaction type
            transaction_type = random.choice(list(TransactionTypeEnum))

            # Set up transaction details based on type
            transaction_id = uuid.uuid4()
            transaction_reference = f"TRN{uuid.uuid4().hex[:8].upper()}"
            transaction_date = start_date + timedelta(
                days=random.randint(0, date_range_days)
            )
            amount = Decimal(str(random.uniform(10.0, 1000.0))).quantize(
                Decimal("0.01")
            )
            description = random.choice(TRANSACTION_DESCRIPTIONS)

            if transaction_type in [
                TransactionTypeEnum.Deposit,
                TransactionTypeEnum.Interest_Credited,
            ]:
                # Credit transaction - money coming in
                transaction = Transaction(
                    id=transaction_id,
                    reference=transaction_reference,
                    amount=amount,
                    description=description,
                    transaction_type=transaction_type,
                    transaction_category=TransactionCategoryEnum.Credit,
                    status=TransactionStatusEnum.Completed,
                    balance_before=Decimal(str(sender_account.balance)) - amount,
                    balance_after=Decimal(str(sender_account.balance)),
                    receiver_account_id=sender_account.id,
                    receiver_id=user_id,
                    processed_by=teller.id if teller else None,
                    created_at=transaction_date,
                    completed_at=transaction_date,
                    transaction_metadata={
                        "currency": sender_account.currency.value,
                        "account_number": sender_account.account_number,
                    },
                    ai_review_status=AIReviewStatusEnum.CLEARED,
                )

            elif transaction_type in [
                TransactionTypeEnum.Withdrawal,
                TransactionTypeEnum.Fee_Charged,
            ]:
                # Debit transaction - money going out
                transaction = Transaction(
                    id=transaction_id,
                    reference=transaction_reference,
                    amount=amount,
                    description=description,
                    transaction_type=transaction_type,
                    transaction_category=TransactionCategoryEnum.Debit,
                    status=TransactionStatusEnum.Completed,
                    balance_before=Decimal(str(sender_account.balance)) + amount,
                    balance_after=Decimal(str(sender_account.balance)),
                    sender_account_id=sender_account.id,
                    sender_id=user_id,
                    processed_by=teller.id if teller else None,
                    created_at=transaction_date,
                    completed_at=transaction_date,
                    transaction_metadata={
                        "currency": sender_account.currency.value,
                        "account_number": sender_account.account_number,
                    },
                    ai_review_status=AIReviewStatusEnum.CLEARED,
                )

            else:  # Transfer
                # Choose a random recipient account (not from the same user)
                other_accounts = [acc for acc in accounts if acc.user_id != user_id]
                if not other_accounts:
                    continue

                receiver_account = random.choice(other_accounts)
                receiver_id = receiver_account.user_id

                transaction = Transaction(
                    id=transaction_id,
                    reference=transaction_reference,
                    amount=amount,
                    description=description,
                    transaction_type=TransactionTypeEnum.Transfer,
                    transaction_category=TransactionCategoryEnum.Debit,
                    status=TransactionStatusEnum.Completed,
                    balance_before=Decimal(str(sender_account.balance)) + amount,
                    balance_after=Decimal(str(sender_account.balance)),
                    sender_account_id=sender_account.id,
                    sender_id=user_id,
                    receiver_account_id=receiver_account.id,
                    receiver_id=receiver_id,
                    created_at=transaction_date,
                    completed_at=transaction_date,
                    transaction_metadata={
                        "from_currency": sender_account.currency.value,
                        "to_currency": receiver_account.currency.value,
                        "account_number": sender_account.account_number,
                        "counterparty_account": receiver_account.account_number,
                    },
                    ai_review_status=AIReviewStatusEnum.CLEARED,
                )

            session.add(transaction)
            transactions.append(transaction)

    # Commit to save transactions
    await session.commit()

    # Mark some transactions as potential fraud for ML training
    fraud_candidates = []
    for transaction in transactions:
        # Select transfers from the last 30 days with higher amounts for fraud candidates
        if (
            transaction.transaction_type == TransactionTypeEnum.Transfer
            and transaction.amount > Decimal("500.0")
            and (today - transaction.created_at).days <= 30
        ):
            fraud_candidates.append(transaction)

    # Choose random transactions to mark as fraud
    if fraud_candidates:
        fraud_transactions = random.sample(
            fraud_candidates, min(num_fraud_transactions, len(fraud_candidates))
        )

        for transaction in fraud_transactions:
            # Mark as flagged or confirmed fraud
            if random.random() > 0.5:
                transaction.ai_review_status = AIReviewStatusEnum.FLAGGED
            else:
                transaction.ai_review_status = AIReviewStatusEnum.CONFIRMED_FRAUD

            # Add risk score for ML training
            risk_score = TransactionRiskScore(
                id=uuid.uuid4(),
                transaction_id=transaction.id,
                risk_score=random.uniform(0.75, 0.99),
                risk_factors={
                    "amount": float(transaction.amount),
                    "time_of_day": transaction.created_at.hour,
                    "unusual_amount": True,
                    "unusual_pattern": True,
                    "velocity": random.uniform(0.7, 0.9),
                },
                ai_model_version="seed_data_v1.0",
                is_confirmed_fraud=transaction.ai_review_status
                == AIReviewStatusEnum.CONFIRMED_FRAUD,
                reviewed_by=(
                    account_executive.id
                    if account_executive
                    and transaction.ai_review_status
                    == AIReviewStatusEnum.CONFIRMED_FRAUD
                    else None
                ),
            )

            session.add(risk_score)

            # Add fraud details to transaction metadata
            if not transaction.transaction_metadata:
                transaction.transaction_metadata = {}

            transaction.transaction_metadata["fraud_review"] = {
                "reviewed_at": datetime.now(UTC).isoformat(),
                "is_fraud": transaction.ai_review_status
                == AIReviewStatusEnum.CONFIRMED_FRAUD,
                "notes": "Suspicious transfer pattern detected during seeding",
            }

            session.add(transaction)

    # Commit all changes
    await session.commit()

    logger.info(
        f"Created {len(transactions)} transactions with "
        f"{num_fraud_transactions} marked as potential fraud"
    )
    return transactions


async def main(
    num_users, num_transactions_per_user, num_fraud_transactions, transaction_date_range
):
    """Main function to seed the database"""
    try:
        # Initialize the database
        await init_db()
        logger.info("Database initialized")

        # Create an async session
        async with async_session() as session:
            # Create users with profiles
            logger.info(f"Creating {num_users} users with profiles...")
            users, admin, account_exec, teller = await create_users_with_profiles(
                session, num_users
            )
            logger.info(f"Created {len(users)} users")
            logger.info(f"Admin user: {admin.email if admin else 'None'}")
            logger.info(
                f"Account Executive: {account_exec.email if account_exec else 'None'}"
            )
            logger.info(f"Teller: {teller.email if teller else 'None'}")

            # Create bank accounts
            logger.info("Creating bank accounts...")
            accounts = await create_bank_accounts(session, users)
            logger.info(f"Created {len(accounts)} bank accounts")

            # Create transactions
            logger.info(
                f"Creating approximately {num_users * num_transactions_per_user} transactions..."
            )
            transactions = await create_transactions(
                session,
                accounts,
                users,
                transaction_date_range,
                num_transactions_per_user,
                num_fraud_transactions,
            )
            logger.info(f"Created {len(transactions)} transactions")

            logger.info("Database seeding completed successfully!")

            # Output some useful information for testing. Credentials are
            # never logged; see the project README for the seeded test
            # password and security answer.
            logger.info("\nTest Accounts Information:")
            logger.info("--------------------------")
            logger.info(f"Admin: email={admin.email if admin else 'None'}")
            logger.info(
                f"Account Executive: email={account_exec.email if account_exec else 'None'}"
            )
            logger.info(f"Teller: email={teller.email if teller else 'None'}")

            # List a few customer accounts
            logger.info("\nSample Customer Accounts:")
            logger.info("--------------------------")
            for i, user in enumerate(
                users[3:8]
            ):  # Skip admin, account exec, and teller
                logger.info(f"Customer {i+1}: email={user.email if user else 'None'}")

            logger.info("\nSample Bank Accounts:")
            logger.info("--------------------------")
            for i, account in enumerate(accounts[:5]):
                logger.info(
                    f"Account {i + 1}: "
                    f"number={account.account_number if account else 'None'}, "
                    f"balance={account.balance if account else 'None'}, "
                    f"currency={account.currency.value if account else 'None'}"
                )

    except Exception as e:
        logger.error(f"Error seeding database: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the database with test data")
    parser.add_argument(
        "--users", type=int, default=NUM_USERS, help="Number of users to create"
    )
    parser.add_argument(
        "--transactions",
        type=int,
        default=NUM_TRANSACTIONS_PER_USER,
        help="Number of transactions per user",
    )
    parser.add_argument(
        "--fraud",
        type=int,
        default=NUM_FRAUD_TRANSACTIONS,
        help="Number of transactions to mark as fraudulent",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=TRANSACTION_DATE_RANGE,
        help="Days to spread transactions over",
    )

    args = parser.parse_args()

    asyncio.run(main(args.users, args.transactions, args.fraud, args.days))
