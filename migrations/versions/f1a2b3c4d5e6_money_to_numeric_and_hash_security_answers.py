"""Money columns to NUMERIC and hash stored security answers.

Monetary values must never live in FLOAT/DOUBLE PRECISION columns: binary
floating point cannot represent decimal cents exactly and errors accumulate
with every arithmetic operation. This migration converts every money column
to NUMERIC(12, 2) (rates to NUMERIC(7, 4)), rounding existing values to the
nearest cent.

It also Argon2-hashes any plaintext ``security_answer`` values on ``user``
rows (values already hashed - starting with ``$argon2`` - are left alone),
matching the application change that stopped storing them in plaintext.

Revision ID: f1a2b3c4d5e6
Revises: ea767da8fc80
Create Date: 2026-07-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "ea767da8fc80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(12, 2)
RATE = sa.Numeric(7, 4)


def _alter_money(table: str, column: str, type_: sa.Numeric, nullable: bool) -> None:
    op.alter_column(
        table,
        column,
        type_=type_,
        existing_nullable=nullable,
        postgresql_using=f"round({column}::numeric, {type_.scale})",
    )


def upgrade() -> None:
    _alter_money("bankaccount", "balance", MONEY, nullable=False)
    _alter_money("bankaccount", "interest_rate", RATE, nullable=False)

    _alter_money("virtualcard", "daily_limit", MONEY, nullable=False)
    _alter_money("virtualcard", "monthly_limit", MONEY, nullable=False)
    _alter_money("virtualcard", "available_balance", MONEY, nullable=False)
    _alter_money("virtualcard", "total_topped_up", MONEY, nullable=False)
    _alter_money("virtualcard", "total_spend_today", MONEY, nullable=False)
    _alter_money("virtualcard", "total_spent_this_month", MONEY, nullable=False)
    _alter_money("virtualcard", "last_transaction_amount", MONEY, nullable=True)

    # Hash plaintext security answers left by earlier application versions.
    from argon2 import PasswordHasher

    hasher = PasswordHasher()
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            'SELECT id, security_answer FROM "user" '
            "WHERE security_answer IS NOT NULL "
            "AND security_answer != '' "
            "AND security_answer NOT LIKE '$argon2%'"
        )
    ).fetchall()

    for row in rows:
        bind.execute(
            sa.text('UPDATE "user" SET security_answer = :hashed WHERE id = :id'),
            {"hashed": hasher.hash(row.security_answer), "id": row.id},
        )


def downgrade() -> None:
    # Hashed security answers are intentionally not reverted (irreversible).
    op.alter_column(
        "virtualcard", "last_transaction_amount", type_=sa.Float(), existing_nullable=True
    )
    for column in (
        "total_spent_this_month",
        "total_spend_today",
        "total_topped_up",
        "available_balance",
        "monthly_limit",
        "daily_limit",
    ):
        op.alter_column("virtualcard", column, type_=sa.Float(), existing_nullable=False)

    op.alter_column("bankaccount", "interest_rate", type_=sa.Float(), existing_nullable=False)
    op.alter_column("bankaccount", "balance", type_=sa.Float(), existing_nullable=False)
