from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.schema import AccountStatusSchema, EmailRequestSchema
from backend.app.auth.service import user_auth_service
from backend.app.auth.utils import create_activation_token
from backend.app.core.db import get_session
from backend.app.core.exceptions import NotFoundError, ValidationFailedError
from backend.app.core.logging import get_logger
from backend.app.core.services.activation_email import send_activation_email

logger = get_logger()

router = APIRouter(prefix="/auth")


@router.get("/activate/{token}", status_code=status.HTTP_200_OK)
async def activate_user(
    token: str,
    session: AsyncSession = Depends(get_session),
):
    """Activate an account from the emailed activation link."""
    user = await user_auth_service.activate_user_account(token, session)
    return {"message": "Account activated successfully", "email": user.email}


@router.post("/resend-activation-link", status_code=status.HTTP_200_OK)
async def resend_activation_link(
    email_data: EmailRequestSchema,
    session: AsyncSession = Depends(get_session),
):
    """Send a fresh activation email for a not-yet-activated account."""
    user = await user_auth_service.get_user_by_email(
        email_data.email, session, include_inactive=True
    )

    if not user:
        raise NotFoundError(
            "If an account exists with this email, please check your inbox "
            "for the activation link"
        )
    if user.is_active or user.account_status == AccountStatusSchema.ACTIVE:
        raise ValidationFailedError(
            "User account already activated",
            action="Please login to your account",
        )

    activation_token = create_activation_token(user.id)
    await send_activation_email(user.email, activation_token)

    return {
        "message": "If an account exists with this email, "
        "please check your inbox for the activation link"
    }
