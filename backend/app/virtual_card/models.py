import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, text
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, Relationship

from backend.app.virtual_card.schema import VirtualCardBaseSchema

if TYPE_CHECKING:
    from backend.app.auth.models import User
    from backend.app.bank_account.models import BankAccount


class VirtualCard(VirtualCardBaseSchema, table=True):
    id: uuid.UUID = Field(
        sa_column=Column(
            pg.UUID(as_uuid=True),
            primary_key=True,
        ),
        default_factory=uuid.uuid4,
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            onupdate=func.current_timestamp(),
        ),
    )
    cvv_hash: str | None = Field(default=None)

    available_balance: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    total_topped_up: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    last_top_up_date: datetime | None = Field(
        default=None,
        sa_column=Column(
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    blocked_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )

    total_spend_today: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    total_spent_this_month: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    last_transaction_date: datetime | None = Field(default=None)
    last_transaction_amount: Decimal | None = Field(
        default=None, max_digits=12, decimal_places=2
    )

    physical_card_requested_at: datetime | None = Field(default=None)
    delivery_address: str | None = Field(default=None)
    delivery_city: str | None = Field(default=None)
    delivery_country: str | None = Field(default=None)
    delivery_postal_code: str | None = Field(default=None)
    physical_card_status: str | None = Field(default=None)

    blocked_by: uuid.UUID | None = Field(foreign_key="user.id", nullable=True)

    card_metadata: dict | None = Field(default=None, sa_column=Column(JSONB))

    bank_account_id: uuid.UUID = Field(foreign_key="bankaccount.id", ondelete="CASCADE")

    bank_account: "BankAccount" = Relationship(back_populates="virtual_cards")
    blocked_by_user: "User" = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "VirtualCard.blocked_by",
        }
    )

    @property
    def masked_card_number(self) -> str:
        if not self.card_number:
            return ""
        return f"**** **** **** {self.card_number[-4:]}"

    @property
    def last_four_digits(self) -> str:
        if not self.card_number:
            return ""
        return self.card_number[-4:]
