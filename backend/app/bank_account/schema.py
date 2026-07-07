from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlmodel import Field, SQLModel

from backend.app.bank_account.enums import (
    AccountCurrencyEnum,
    AccountStatusEnum,
    AccountTypeEnum,
)


class BankAccountBaseSchema(SQLModel):
    """Shared bank account fields.

    Monetary columns use ``Decimal`` (NUMERIC in PostgreSQL): floats must
    never hold money because binary floating point cannot represent cents
    exactly and rounding errors accumulate.
    """

    account_type: AccountTypeEnum
    currency: AccountCurrencyEnum
    account_status: AccountStatusEnum = Field(default=AccountStatusEnum.Pending)
    account_number: str | None = Field(default=None, unique=True, index=True)
    account_name: str
    balance: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)
    is_primary: bool = Field(default=False)
    kyc_submitted: bool = Field(default=False)
    kyc_verified: bool = Field(default=False)
    kyc_verified_by: UUID | None = Field(default=None)
    interest_rate: Decimal = Field(default=Decimal("0.0000"), max_digits=7, decimal_places=4)


class BankAccountCreateSchema(BankAccountBaseSchema):
    account_number: str | None = None


class BankAccountReadSchema(BankAccountBaseSchema):
    id: UUID
    user_id: UUID
    account_number: str | None = None
    created_at: datetime
    updated_at: datetime


class BankAccountUpdateSchema(BankAccountBaseSchema):
    account_name: str | None = None
    is_primary: bool | None = None
    account_status: AccountStatusEnum | None = None
