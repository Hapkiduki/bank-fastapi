from fastapi import APIRouter, Response, status

from backend.app.auth.utils import delete_auth_cookies
from backend.app.core.logging import get_logger

logger = get_logger()

router = APIRouter(prefix="/auth")


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(response: Response) -> dict:
    """Clear the auth cookies."""
    delete_auth_cookies(response)
    logger.info("User logged out successfully")
    return {"message": "Logged out successfully"}
