from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Response, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import CurrentUser
from backend.app.bank_account.enums import AccountStatusEnum
from backend.app.bank_account.models import BankAccount
from backend.app.core.celery_app import celery_app
from backend.app.core.db import get_session
from backend.app.core.exceptions import NotFoundError, ValidationFailedError
from backend.app.core.logging import get_logger
from backend.app.transaction.schema import (
    StatementRequestSchema,
    StatementResponseSchema,
)
from backend.app.transaction.service import generate_user_statement

logger = get_logger()
router = APIRouter(prefix="/bank-account")


@router.post(
    "/statement/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_statement(
    request: StatementRequestSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> StatementResponseSchema:
    """Queue asynchronous PDF statement generation for the user's accounts."""
    if request.start_date > request.end_date:
        raise ValidationFailedError("Start date must be before end date")

    if request.account_number:
        account_query = select(BankAccount).where(
            BankAccount.account_number == request.account_number,
            BankAccount.user_id == current_user.id,
        )
        result = await session.exec(account_query)
        account = result.first()

        if not account:
            raise NotFoundError("Account not found or does not belong to you")

        if account.account_status != AccountStatusEnum.Active:
            raise ValidationFailedError(
                "Cannot generate statement for inactive account"
            )

    result = await generate_user_statement(
        user_id=current_user.id,
        start_date=request.start_date,
        end_date=request.end_date,
        session=session,
        account_number=request.account_number,
    )

    generated_at = datetime.now(UTC)
    expires_at = generated_at + timedelta(hours=1)

    return StatementResponseSchema(
        status="pending",
        message="Statement generation initiated",
        task_id=result["task_id"],
        statement_id=result["statement_id"],
        generated_at=generated_at,
        expires_at=expires_at,
    )


@router.get("/statement/{statement_id}")
async def get_statement(statement_id: str) -> Response:
    """Download a previously generated PDF statement from Redis."""
    redis_client = celery_app.backend.client
    pdf_data = redis_client.get(f"statement:{statement_id}")
    if not pdf_data:
        raise NotFoundError("Statement not found or has expired")
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment;filename=statement_{statement_id}.pdf"
        },
    )
