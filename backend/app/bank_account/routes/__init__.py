"""HTTP routes for the bank account feature (account lifecycle)."""

from fastapi import APIRouter

from backend.app.bank_account.routes import activate, create

router = APIRouter()
router.include_router(create.router)
router.include_router(activate.router)
