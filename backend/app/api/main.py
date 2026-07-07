"""API composition root.

Each feature package (vertical slice) exposes a single aggregated router from
its ``routes`` subpackage; this module wires them all under one ``APIRouter``
that ``backend.app.main`` mounts with the versioned API prefix.
"""

from fastapi import APIRouter

from backend.app.api import home
from backend.app.auth.routes import router as auth_router
from backend.app.bank_account.routes import router as bank_account_router
from backend.app.core.ml.routes import router as ml_router
from backend.app.next_of_kin.routes import router as next_of_kin_router
from backend.app.transaction.routes import router as transaction_router
from backend.app.user_profile.routes import router as user_profile_router
from backend.app.virtual_card.routes import router as virtual_card_router

api_router = APIRouter()

api_router.include_router(home.router)
api_router.include_router(auth_router)
api_router.include_router(user_profile_router)
api_router.include_router(next_of_kin_router)
api_router.include_router(bank_account_router)
api_router.include_router(transaction_router)
api_router.include_router(virtual_card_router)
api_router.include_router(ml_router)
