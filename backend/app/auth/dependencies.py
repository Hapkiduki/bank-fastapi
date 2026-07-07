"""Authentication dependencies: current-user resolution and role guards."""

from typing import Annotated

import jwt
from fastapi import Cookie, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.models import User
from backend.app.auth.schema import RoleChoicesSchema
from backend.app.core.config import settings
from backend.app.core.db import get_session
from backend.app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from backend.app.core.logging import get_logger

logger = get_logger()


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    access_token: str | None = Cookie(None, alias=settings.COOKIE_ACCESS_NAME),
) -> User:
    """Resolve the authenticated user from the access-token cookie.

    Validates the JWT signature, expiry and token type, loads the user and
    checks the account is active and not locked.
    """
    if not access_token:
        raise UnauthorizedError(
            "Not Authenticated",
            action="Please login to access this resource",
        )

    try:
        payload = jwt.decode(
            access_token,
            settings.SIGNING_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError(
            "Token has expired", action="Please log in again"
        ) from None
    except jwt.InvalidTokenError:
        raise UnauthorizedError(
            "Invalid token", action="Please log in again"
        ) from None

    if payload.get("type") != settings.COOKIE_ACCESS_NAME:
        raise UnauthorizedError(
            "Invalid token type",
            action="Please login to access this resource",
        )

    from backend.app.auth.service import user_auth_service

    user = await user_auth_service.get_user_by_id(payload["id"], session)
    if not user:
        raise NotFoundError("User not found", action="Please login again")

    await user_auth_service.validate_user_status(user)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(role: RoleChoicesSchema, message: str):
    """Build a dependency that only lets users with ``role`` through.

    Usage::

        current_user: User = Depends(
            require_role(RoleChoicesSchema.TELLER, "Only tellers can ...")
        )
    """

    async def dependency(current_user: CurrentUser) -> User:
        if current_user.role != role:
            raise ForbiddenError(message)
        return current_user

    return dependency
