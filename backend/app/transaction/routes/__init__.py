"""HTTP routes for the transaction feature (money movement and fraud review)."""

from fastapi import APIRouter

from backend.app.transaction.routes import (
    deposit,
    fraud_review,
    risk_history,
    statement,
    transaction_history,
    transfer,
    withdrawal,
)

router = APIRouter()
router.include_router(deposit.router)
router.include_router(transfer.router)
router.include_router(withdrawal.router)
router.include_router(transaction_history.router)
router.include_router(statement.router)
router.include_router(fraud_review.router)
router.include_router(risk_history.router)
