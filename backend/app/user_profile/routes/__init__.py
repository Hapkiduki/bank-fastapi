"""HTTP routes for the user profile feature."""

from fastapi import APIRouter

from backend.app.user_profile.routes import all_profiles, create, me, update, upload

router = APIRouter()
router.include_router(create.router)
router.include_router(update.router)
router.include_router(upload.router)
router.include_router(me.router)
router.include_router(all_profiles.router)
