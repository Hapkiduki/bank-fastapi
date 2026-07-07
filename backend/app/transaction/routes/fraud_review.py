from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import require_role
from backend.app.auth.models import User
from backend.app.auth.schema import RoleChoicesSchema
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.transaction.schema import TransactionReviewSchema
from backend.app.transaction.service import review_flagged_transaction

logger = get_logger()
router = APIRouter(prefix="/transaction")


@router.post(
    "/{transaction_id}/review",
    status_code=status.HTTP_200_OK,
    description="Review a flagged transaction. Only available to account executives",
)
async def review_transaction(
    transaction_id: UUID,
    review_data: TransactionReviewSchema,
    current_user: User = Depends(
        require_role(
            RoleChoicesSchema.ACCOUNT_EXECUTIVE,
            "Only account executives can review transactions",
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Human decision for an AI-flagged transaction (approve or confirm fraud)."""
    return await review_flagged_transaction(
        transaction_id=transaction_id,
        reviewer_id=current_user.id,
        is_fraud=review_data.is_fraud,
        notes=review_data.notes,
        session=session,
        approve_transaction=review_data.approve_transaction,
    )
