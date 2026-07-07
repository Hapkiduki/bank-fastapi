from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.dependencies import require_role
from backend.app.auth.models import User
from backend.app.auth.schema import RoleChoicesSchema
from backend.app.core.db import get_session
from backend.app.core.exceptions import ValidationFailedError
from backend.app.core.logging import get_logger
from backend.app.transaction.schema import (
    PaginatedHistoryResponseSchema,
    RiskHistoryItemSchema,
    RiskHistoryParams,
)
from backend.app.transaction.service import get_user_risk_history

logger = get_logger()
router = APIRouter(prefix="/transaction")


def get_risk_history_params(
    start_date: datetime | None = Query(
        default=None, description="Filter from this date"
    ),
    end_date: datetime | None = Query(
        default=None, description="Filter until this date"
    ),
    min_risk_score: float | None = Query(
        default=None, ge=0, le=1, description="Minimum risk score"
    ),
    user_id: str | None = Query(
        default=None,
        description="Filter by specific user ID (only for account executives)",
    ),
    skip: int = Query(
        default=0, ge=0, description="Number of records to skip(for pagination)"
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of records to return (for pagination)",
    ),
) -> RiskHistoryParams:
    return RiskHistoryParams(
        start_date=start_date,
        end_date=end_date,
        min_risk_score=min_risk_score,
        user_id=user_id,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/risk-history",
    status_code=status.HTTP_200_OK,
    description="Get paginated risk analysis history for transactions. "
    "Only accessible to account executives.",
)
async def get_risk_history(
    current_user: User = Depends(
        require_role(
            RoleChoicesSchema.ACCOUNT_EXECUTIVE,
            "Only account executives can view transaction risk history",
        )
    ),
    params: RiskHistoryParams = Depends(get_risk_history_params),
    session: AsyncSession = Depends(get_session),
) -> PaginatedHistoryResponseSchema:
    """Paginated fraud-risk history, optionally filtered by user."""
    if params.user_id:
        try:
            target_user_id = UUID(params.user_id)
        except ValueError:
            raise ValidationFailedError("Invalid user ID format") from None
    else:
        target_user_id = current_user.id

    history_dicts, total_count = await get_user_risk_history(
        user_id=target_user_id,
        start_date=params.start_date,
        end_date=params.end_date,
        min_risk_score=params.min_risk_score,
        skip=params.skip,
        limit=params.limit,
        session=session,
    )

    history_items = [
        RiskHistoryItemSchema.model_validate(item) for item in history_dicts
    ]
    return PaginatedHistoryResponseSchema(
        total=total_count, skip=params.skip, limit=params.limit, items=history_items
    )
