"""Authentication business logic: user lookup, registration, activation,
OTP login, lockout policy and password reset."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.models import User
from backend.app.auth.schema import AccountStatusSchema, UserCreateSchema
from backend.app.auth.utils import (
    create_activation_token,
    generate_otp,
    generate_password_hash,
    generate_username,
    hash_security_answer,
    verify_password,
)
from backend.app.core.config import settings
from backend.app.core.exceptions import (
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)
from backend.app.core.logging import get_logger
from backend.app.core.services.account_lockout import send_account_lockout_email
from backend.app.core.services.activation_email import send_activation_email
from backend.app.core.services.login_otp import send_login_otp_email

logger = get_logger()


class UserAuthService:
    """Stateless service encapsulating every auth-related use case.

    A single module-level instance (``user_auth_service``) is shared across
    requests; all state lives in the database session passed per call.
    """

    async def get_user_by_email(
        self, email: str, session: AsyncSession, include_inactive: bool = False
    ) -> User | None:
        statement = select(User).where(User.email == email)

        if not include_inactive:
            statement = statement.where(User.is_active)
        result = await session.exec(statement)
        user = result.first()
        return user

    async def get_user_by_id_no(
        self, id_no: int, session: AsyncSession, include_inactive: bool = False
    ) -> User | None:
        statement = select(User).where(User.id_no == id_no)

        if not include_inactive:
            statement = statement.where(User.is_active)
        result = await session.exec(statement)
        user = result.first()
        return user

    async def get_user_by_id(
        self,
        id: uuid.UUID,
        session: AsyncSession,
        include_inactive: bool = False,
    ) -> User | None:
        statement = select(User).where(User.id == id)

        if not include_inactive:
            statement = statement.where(User.is_active)
        result = await session.exec(statement)
        user = result.first()
        return user

    async def check_user_email_exists(self, email: str, session: AsyncSession) -> bool:
        user = await self.get_user_by_email(email, session)
        return bool(user)

    async def check_user_id_no_exists(self, id_no: int, session: AsyncSession) -> bool:
        user = await self.get_user_by_id_no(id_no, session)
        return bool(user)

    async def verify_user_password(
        self, plain_password: str, hashed_password: str
    ) -> bool:
        return verify_password(plain_password, hashed_password)

    async def reset_user_state(
        self,
        user: User,
        session: AsyncSession,
        *,
        clear_otp: bool = True,
        log_action: bool = True,
    ) -> None:
        """Clear failed-attempt counters (and optionally the OTP), unlocking
        the account if the lockout has been served."""
        previous_status = user.account_status

        user.failed_login_attempts = 0
        user.last_failed_login = None

        if clear_otp:
            user.otp = ""
            user.otp_expiry_time = None

        if user.account_status == AccountStatusSchema.LOCKED:
            user.account_status = AccountStatusSchema.ACTIVE

        await session.commit()

        await session.refresh(user)

        if log_action and previous_status != user.account_status:
            logger.info(
                f"User {user.email} state reset: {previous_status} -> {user.account_status}"
            )

    async def validate_user_status(self, user: User) -> None:
        """Reject users that are not allowed to authenticate."""
        if not user.is_active:
            raise ValidationFailedError(
                "Your account is not activated",
                action="Please activate your account first",
            )

        if user.account_status == AccountStatusSchema.LOCKED:
            raise ValidationFailedError(
                "Your account is locked",
                action="Please contact support",
            )

        if user.account_status == AccountStatusSchema.INACTIVE:
            raise ValidationFailedError(
                "Your account is inactive",
                action="Please activate your account",
            )

    async def generate_and_save_otp(
        self,
        user: User,
        session: AsyncSession,
    ) -> tuple[bool, str]:
        """Issue a login OTP and email it, retrying delivery up to 3 times.

        The OTP is cleared again if every delivery attempt fails, so a user
        can immediately request a fresh one.
        """
        try:
            otp = generate_otp()
            user.otp = otp

            user.otp_expiry_time = datetime.now(UTC) + timedelta(
                minutes=settings.OTP_EXPIRATION_MINUTES
            )

            await session.commit()
            await session.refresh(user)

            for attempt in range(3):
                try:
                    await send_login_otp_email(user.email, otp)
                    logger.info(f"OTP sent to {user.email} successfully")
                    return True, otp
                except Exception as e:
                    logger.error(
                        f"Failed to send OTP email (attempt {attempt + 1}): {e}"
                    )
                    if attempt == 2:
                        user.otp = ""
                        user.otp_expiry_time = None
                        await session.commit()
                        await session.refresh(user)
                        return False, ""

                    await asyncio.sleep(2**attempt)
            return False, ""

        except Exception as e:
            logger.error(f"Failed to generate and save OTP: {e}")

            user.otp = ""
            user.otp_expiry_time = None
            await session.commit()
            await session.refresh(user)
            return False, ""

    async def create_user(
        self,
        user_data: UserCreateSchema,
        session: AsyncSession,
    ) -> User:
        """Register a new (inactive) user and send the activation email.

        The password and the security answer are both Argon2-hashed before
        they touch the database.
        """
        user_data_dict = user_data.model_dump(
            exclude={"confirm_password", "username", "is_active", "account_status"}
        )

        password = user_data_dict.pop("password")
        security_answer = user_data_dict.pop("security_answer")

        new_user = User(
            username=generate_username(),
            hashed_password=generate_password_hash(password),
            security_answer=hash_security_answer(security_answer),
            is_active=False,
            account_status=AccountStatusSchema.PENDING,
            **user_data_dict,
        )

        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        activation_token = create_activation_token(new_user.id)
        try:
            await send_activation_email(new_user.email, activation_token)
            logger.info(f"Activation email sent to {new_user.email}")

        except Exception as e:
            logger.error(f"Failed to send activation email to {new_user.email}: {e}")
            raise

        return new_user

    async def activate_user_account(
        self,
        token: str,
        session: AsyncSession,
    ) -> User:
        """Activate an account from the emailed activation JWT."""
        invalid_token_error = ValidationFailedError(
            "Invalid activation token",
            action="Please confirm that the link you clicked on is correct",
        )
        try:
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
        except jwt.ExpiredSignatureError:
            raise ValidationFailedError(
                "Activation link has expired",
                action="Please request a new activation link",
                status_code=status.HTTP_410_GONE,
                extra={
                    "action_url": (
                        f"{settings.API_BASE_URL}{settings.API_V1_STR}"
                        "/auth/resend-activation-link"
                    ),
                    "email_required": True,
                },
            ) from None
        except jwt.InvalidTokenError:
            raise invalid_token_error from None

        if payload.get("type") != "activation":
            raise invalid_token_error

        user_id = uuid.UUID(payload["id"])

        user = await self.get_user_by_id(user_id, session, include_inactive=True)

        if not user:
            raise NotFoundError("User not found")
        if user.is_active:
            raise ValidationFailedError(
                "User already activated",
                action="Please login to your account",
            )

        await self.reset_user_state(user, session, clear_otp=True, log_action=True)

        user.is_active = True
        user.account_status = AccountStatusSchema.ACTIVE

        await session.commit()
        await session.refresh(user)

        return user

    async def verify_login_otp(
        self,
        email: str,
        otp: str,
        session: AsyncSession,
    ) -> User:
        """Validate a login OTP.

        Wrong OTPs count towards the failed-attempt lockout, so an attacker
        cannot brute-force the 6-digit code.
        """
        user = await self.get_user_by_email(email, session)
        if not user:
            raise UnauthorizedError("Invalid credentials")

        await self.validate_user_status(user)

        await self.check_user_lockout(user, session)

        if not user.otp or user.otp != otp:
            await self.increment_failed_login_attempts(user, session)
            raise ValidationFailedError(
                "Invalid OTP",
                action="Please check your OTP and try again",
            )

        if user.otp_expiry_time is None or user.otp_expiry_time < datetime.now(
            UTC
        ):
            raise ValidationFailedError(
                "OTP has expired",
                action="Please request a new OTP",
            )

        await self.reset_user_state(user, session, clear_otp=False)

        return user

    async def check_user_lockout(
        self,
        user: User,
        session: AsyncSession,
    ) -> None:
        """Enforce the temporary lockout window after repeated failures."""
        if user.account_status != AccountStatusSchema.LOCKED:
            return

        if user.last_failed_login is None:
            return

        lockout_time = user.last_failed_login + timedelta(
            minutes=settings.LOCKOUT_DURATION_MINUTES
        )

        current_time = datetime.now(UTC)

        if current_time >= lockout_time:
            await self.reset_user_state(user, session, clear_otp=False)
            logger.info(f"Lockout period ended for user {user.email}")
            return

        remaining_minutes = int((lockout_time - current_time).total_seconds() / 60)

        logger.warning(f"Attempted login to locked account: {user.email}")
        raise ValidationFailedError(
            "Your account is temporarily locked",
            action=f"Please try again after {remaining_minutes} minutes",
            extra={"lockout_remaining_minutes": remaining_minutes},
        )

    async def increment_failed_login_attempts(
        self,
        user: User,
        session: AsyncSession,
    ) -> None:
        """Count a failed attempt, locking the account past the threshold.

        Locking also invalidates any outstanding OTP so it cannot be replayed
        once the lockout expires.
        """
        user.failed_login_attempts += 1

        current_time = datetime.now(UTC)
        user.last_failed_login = current_time

        if user.failed_login_attempts >= settings.LOGIN_ATTEMPTS:
            user.account_status = AccountStatusSchema.LOCKED
            user.otp = ""
            user.otp_expiry_time = None

            try:
                await send_account_lockout_email(user.email, current_time)
                logger.info(f"Account lockout notification email sent to {user.email}")

            except Exception as e:
                logger.error(
                    f"Failed to send account lockout email to {user.email}: {e}"
                )
            logger.warning(
                f"User {user.email} has been locked out due to too many failed login attempts"
            )
        await session.commit()

        await session.refresh(user)

    async def reset_password(
        self,
        token: str,
        new_password: str,
        session: AsyncSession,
    ) -> None:
        """Set a new password from the emailed password-reset JWT."""
        reset_action = "Please request a new password reset link."
        try:
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
        except jwt.ExpiredSignatureError:
            raise ValidationFailedError(
                "Password reset token expired", action=reset_action
            ) from None
        except jwt.InvalidTokenError:
            raise ValidationFailedError(
                "Invalid password reset token", action=reset_action
            ) from None

        if payload.get("type") != "password_reset":
            raise ValidationFailedError(
                "Invalid password reset token", action=reset_action
            )

        user_id = uuid.UUID(payload["id"])

        user = await self.get_user_by_id(user_id, session, include_inactive=True)

        if not user:
            raise NotFoundError("User not found")

        user.hashed_password = generate_password_hash(new_password)

        await self.reset_user_state(user, session, clear_otp=True, log_action=True)

        await session.commit()
        await session.refresh(user)

        logger.info(f"Password reset successful for user {user.email}")


user_auth_service = UserAuthService()
