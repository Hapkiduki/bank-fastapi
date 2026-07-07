"""HTTP routes for the virtual card feature."""

from fastapi import APIRouter

from backend.app.virtual_card.routes import activate, block, create, delete, topup

router = APIRouter()
router.include_router(create.router)
router.include_router(activate.router)
router.include_router(block.router)
router.include_router(topup.router)
router.include_router(delete.router)
