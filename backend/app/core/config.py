from pathlib import Path
from typing import Literal

import cloudinary
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_DIR = PROJECT_ROOT / ".envs"


class Settings(BaseSettings):
    """Central application settings.

    Values are resolved with the following precedence (highest wins):

    1. Real environment variables (what docker compose injects via ``env_file``).
    2. ``.envs/.env.local`` (developer machine overrides, git-ignored).
    3. ``.envs/.env.production`` (server-side file, never committed).
    4. Field defaults declared below.

    ``ENVIRONMENT`` defaults to ``production`` on purpose (secure by default):
    an unconfigured deployment gets the strictest cookie/expiry settings.
    Environment-dependent values are exposed as properties so they always
    reflect the *runtime* ``ENVIRONMENT`` value, not the class-definition
    default.
    """

    ENVIRONMENT: Literal["local", "staging", "production"] = "production"

    model_config = SettingsConfigDict(
        # Later files take precedence; both are optional (containers rely on
        # real env vars injected by compose, not on these files).
        env_file=(ENV_DIR / ".env.production", ENV_DIR / ".env.local"),
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = ""
    PROJECT_NAME: str = ""
    PROJECT_DESCRIPTION: str = ""
    SITE_NAME: str = ""
    DATABASE_URL: str = ""
    MAIL_FROM: str = ""
    MAIL_FROM_NAME: str = ""
    MAILGUN_SMTP_SERVER: str = "smtp.mailgun.org"
    MAILGUN_SMTP_PORT: int = 587
    MAILGUN_SMTP_USERNAME: str = ""
    MAILGUN_SMTP_PASSWORD: str = ""

    SMTP_HOST: str = "mailpit"
    SMTP_PORT: int = 1025
    MAILPIT_UI_PORT: int = 8025

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    RABBITMQ_HOST: str = "rabbitmq"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "guest"
    RABBITMQ_PASSWORD: str = "guest"

    LOGIN_ATTEMPTS: int = 3
    API_BASE_URL: str = ""
    SUPPORT_EMAIL: str = ""
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_REFRESH_TOKEN_EXPIRATION_DAYS: int = 1
    COOKIE_ACCESS_NAME: str = "access_token"
    COOKIE_REFRESH_NAME: str = "refresh_token"
    COOKIE_LOGGED_IN_NAME: str = "logged_in"

    COOKIE_HTTP_ONLY: bool = True
    COOKIE_SAMESITE: str = "lax"
    COOKIE_PATH: str = "/"
    SIGNING_KEY: str = ""

    CORS_ORIGINS: list[str] = []

    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    ALLOWED_MIME_TYPES: list[str] = ["image/jpeg", "image/png", "image/jpg"]
    MAX_FILE_SIZE: int = 5 * 1024 * 1024
    MAX_DIMENSION: int = 4096

    BANK_CODE: str = ""
    BANK_BRANCH_CODE: str = ""
    CURRENCY_CODE_USD: str = "01"
    CURRENCY_CODE_EUR: str = "02"
    CURRENCY_CODE_GBP: str = "03"
    CURRENCY_CODE_KES: str = "04"
    MAX_BANK_ACCOUNTS: int = 3

    @property
    def is_local(self) -> bool:
        """Whether the app is running in the local development environment."""
        return self.ENVIRONMENT == "local"

    @property
    def OTP_EXPIRATION_MINUTES(self) -> int:
        """OTP lifetime: short in local for fast iteration, longer elsewhere."""
        return 2 if self.is_local else 5

    @property
    def LOCKOUT_DURATION_MINUTES(self) -> int:
        """How long an account stays locked after too many failed logins."""
        return 2 if self.is_local else 5

    @property
    def ACTIVATION_TOKEN_EXPIRATION_MINUTES(self) -> int:
        """Lifetime of the account-activation JWT sent by email."""
        return 2 if self.is_local else 5

    @property
    def JWT_ACCESS_TOKEN_EXPIRATION_MINUTES(self) -> int:
        """Access-token lifetime; shorter in production."""
        return 30 if self.is_local else 15

    @property
    def PASSWORD_RESET_TOKEN_EXPIRATION_MINUTES(self) -> int:
        """Lifetime of the password-reset JWT sent by email."""
        return 3 if self.is_local else 5

    @property
    def COOKIE_SECURE(self) -> bool:
        """Secure flag for auth cookies; disabled locally (plain HTTP)."""
        return not self.is_local

    @model_validator(mode="after")
    def _require_signing_secrets(self) -> "Settings":
        """Fail fast when JWT secrets are missing.

        Signing tokens with an empty key would let anyone forge valid
        credentials, so the app refuses to start without both secrets.
        """
        missing = [
            name
            for name in ("JWT_SECRET_KEY", "SIGNING_KEY")
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                f"Missing required security settings: {', '.join(missing)}. "
                "Set them in the environment or in .envs/.env.local "
                "(e.g. generate one with: openssl rand -hex 32)."
            )
        return self


settings = Settings()

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
)
