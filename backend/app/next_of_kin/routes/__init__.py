"""HTTP routes for the next-of-kin feature."""

from fastapi import APIRouter

from backend.app.next_of_kin.routes import all, create, delete, update

router = APIRouter()
router.include_router(create.router)
router.include_router(all.router)
router.include_router(update.router)
router.include_router(delete.router)
