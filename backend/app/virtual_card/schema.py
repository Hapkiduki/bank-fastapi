from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field
from sqlmodel import SQLModel

from backend.app.virtual_card.enums import (
    CardBlockReasonEnum,
    VirtualCardBrandEnum,
    VirtualCardCurrencyEnum,
    VirtualCardStatusEnum,
    VirtualCardTypeEnum,
)


class VirtualCardBaseSchema(SQLModel):
    card_type: VirtualCardTypeEnum
    card_brand: VirtualCardBrandEnum = Field(default=VirtualCardBrandEnum.Visa)
    currency: VirtualCardCurrencyEnum
    card_status: VirtualCardStatusEnum = Field(default=VirtualCardStatusEnum.Pending)
    daily_limit: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    monthly_limit: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    name_on_card: str = Field(max_length=50)
    expiry_date: date
    is_active: bool = Field(default=True)
    is_physical_card_requested: bool = Field(default=False)
    block_reason: CardBlockReasonEnum | None = None
    block_reason_description: str | None = Field(default=None)
    card_number: str | None = Field(default=None)
    card_metadata: dict | None = Field(default=None)


class VirtualCardCreateSchema(VirtualCardBaseSchema):
    bank_account_id: UUID
    expiry_date: date | None = None


class VirtualCardReadSchema(VirtualCardBaseSchema):
    id: UUID
    bank_account_id: UUID
    last_four_digits: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class VirtualCardUpdateSchema(VirtualCardBaseSchema):
    daily_limit: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    monthly_limit: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    is_active: bool | None = Field(default=None)


class VirtualCardBlockSchema(VirtualCardBaseSchema):
    block_reason: CardBlockReasonEnum = Field()
    block_reason_description: str = Field()
    blocked_at: datetime = Field()
    blocked_by: UUID = Field()


class VirtualCardStatusSchema(VirtualCardBaseSchema):
    card_status: VirtualCardStatusEnum = Field()
    available_balance: Decimal
    daily_limit: Decimal = Field()
    monthly_limit: Decimal = Field()
    total_spend_today: Decimal
    total_spend_this_month: Decimal
    last_transaction_date: datetime | None = None
    last_transaction_amount: Decimal | None = None


class PhysicalCardRequestSchema(SQLModel):
    delivery_address: str = Field(max_length=200)
    city: str = Field(max_length=100)
    country: str = Field(max_length=100)
    postal_code: str = Field(max_length=20)


class CardTopUpSchema(SQLModel):
    account_number: str = Field(min_length=16, max_length=16)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    description: str = Field(max_length=250)


class CardTopUpResponseSchema(SQLModel):
    status: str
    message: str
    data: dict | None = None


class CardDeleteResponseSchema(SQLModel):
    status: str
    message: str
    deleted_at: datetime


class CardBlockSchema(SQLModel):
    block_reason: CardBlockReasonEnum
    block_reason_description: str = Field(max_length=250)
