"""HTTP routes for the auth feature (registration, activation, login, tokens)."""

from fastapi import APIRouter

from backend.app.auth.routes import (
    activate,
    login,
    logout,
    password_reset,
    refresh,
    register,
)

router = APIRouter()
router.include_router(register.router)
router.include_router(activate.router)
router.include_router(login.router)
router.include_router(password_reset.router)
router.include_router(refresh.router)
router.include_router(logout.router)
