"""Auth helpers: OTP generation, Argon2 hashing, JWT creation and cookies."""

import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Response

from backend.app.core.config import settings

_ph = PasswordHasher()


def generate_otp(length: int = 6) -> str:
    """Generate a numeric one-time password using a CSPRNG."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_password_hash(password: str) -> str:
    """Hash a password with Argon2id."""
    return _ph.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Constant-time Argon2 verification; returns False on mismatch."""
    try:
        return _ph.verify(hashed_password, password)
    except VerifyMismatchError:
        return False


def hash_security_answer(answer: str) -> str:
    """Hash the security answer with Argon2 (never stored in plaintext)."""
    return _ph.hash(answer)


def verify_security_answer(answer: str, hashed_answer: str) -> bool:
    """Verify a security answer against its Argon2 hash."""
    try:
        return _ph.verify(hashed_answer, answer)
    except VerifyMismatchError:
        return False
    except Exception:
        # Covers malformed/legacy plaintext values left in the column.
        return False


def generate_username() -> str:
    """Generate a bank-prefixed random username (e.g. ``B-4G7KQ2XM9D``)."""
    bank_name = settings.SITE_NAME
    words = bank_name.split()
    prefix = "".join([word[0] for word in words]).upper()
    remaining_length = 12 - len(prefix) - 1
    alphabet = string.ascii_uppercase + string.digits
    random_string = "".join(secrets.choice(alphabet) for _ in range(remaining_length))
    username = f"{prefix}-{random_string}"

    return username


def create_activation_token(id: uuid.UUID) -> str:
    payload = {
        "id": str(id),
        "type": "activation",
        "exp": datetime.now(UTC)
        + timedelta(minutes=settings.ACTIVATION_TOKEN_EXPIRATION_MINUTES),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def create_jwt_token(id: uuid.UUID, type: str = settings.COOKIE_ACCESS_NAME) -> str:
    if type == settings.COOKIE_ACCESS_NAME:
        expire_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRATION_MINUTES)
    else:
        expire_delta = timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRATION_DAYS)

    payload = {
        "id": str(id),
        "type": type,
        "exp": datetime.now(UTC) + expire_delta,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.SIGNING_KEY, algorithm=settings.JWT_ALGORITHM)


def set_auth_cookies(
    response: Response, access_token: str, refresh_token: str | None = None
) -> None:
    cookie_settings = {
        "path": settings.COOKIE_PATH,
        "secure": settings.COOKIE_SECURE,
        "httponly": settings.COOKIE_HTTP_ONLY,
        "samesite": settings.COOKIE_SAMESITE,
    }
    access_cookie_settings = cookie_settings.copy()
    access_cookie_settings["max_age"] = (
        settings.JWT_ACCESS_TOKEN_EXPIRATION_MINUTES * 60
    )

    response.set_cookie(
        settings.COOKIE_ACCESS_NAME, access_token, **access_cookie_settings
    )

    if refresh_token:
        refresh_cookie_settings = cookie_settings.copy()
        refresh_cookie_settings["max_age"] = (
            settings.JWT_REFRESH_TOKEN_EXPIRATION_DAYS * 24 * 60 * 60
        )
        response.set_cookie(
            settings.COOKIE_REFRESH_NAME,
            refresh_token,
            **refresh_cookie_settings,
        )

    logged_in_cookie_settings = cookie_settings.copy()
    logged_in_cookie_settings["httponly"] = False
    logged_in_cookie_settings["max_age"] = (
        settings.JWT_ACCESS_TOKEN_EXPIRATION_MINUTES * 60
    )

    response.set_cookie(
        settings.COOKIE_LOGGED_IN_NAME,
        "true",
        **logged_in_cookie_settings,
    )


def delete_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.COOKIE_ACCESS_NAME)
    response.delete_cookie(settings.COOKIE_REFRESH_NAME)
    response.delete_cookie(settings.COOKIE_LOGGED_IN_NAME)


def create_password_reset_token(id: uuid.UUID) -> str:
    payload = {
        "id": str(id),
        "type": "password_reset",
        "exp": datetime.now(UTC)
        + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRATION_MINUTES),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
