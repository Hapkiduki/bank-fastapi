"""Domain exception hierarchy and global exception handlers.

Services and routes raise these typed exceptions instead of building
``HTTPException`` objects inline. A single set of handlers registered on the
FastAPI app translates them into the canonical error envelope::

    {"detail": {"status": "error", "message": "...", "action": "...", ...}}

which is byte-compatible with the response shape the API produced before the
handlers were centralized. Unexpected exceptions are logged with a traceback
and mapped to an opaque 500 so internals never leak to clients.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from backend.app.core.logging import get_logger

logger = get_logger()


class BankAPIError(Exception):
    """Base class for expected (domain) errors raised by the banking API.

    Attributes:
        status_code: HTTP status the handler responds with. Subclasses set a
            sensible default; instances may override it via the constructor.
        message: Human-readable error description shown to the client.
        action: Optional hint telling the client what to do next.
        extra: Optional additional payload merged into the error body
            (e.g. risk analysis details for flagged transactions).
    """

    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: str,
        *,
        action: str | None = None,
        extra: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.action = action
        self.extra = extra or {}
        if status_code is not None:
            self.status_code = status_code

    def payload(self) -> dict[str, Any]:
        """Build the error body placed under the ``detail`` key."""
        body: dict[str, Any] = {"status": "error", "message": self.message}
        if self.action:
            body["action"] = self.action
        body.update(self.extra)
        return body


class NotFoundError(BankAPIError):
    """A referenced resource (user, account, transaction...) does not exist."""

    status_code = status.HTTP_404_NOT_FOUND


class UnauthorizedError(BankAPIError):
    """Authentication failed or the credential presented is invalid/expired."""

    status_code = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(BankAPIError):
    """The authenticated user is not allowed to perform this operation."""

    status_code = status.HTTP_403_FORBIDDEN


class ConflictError(BankAPIError):
    """The request conflicts with current state (duplicates, limits reached)."""

    status_code = status.HTTP_409_CONFLICT


class ValidationFailedError(BankAPIError):
    """Business-rule validation failed (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST


class InsufficientBalanceError(ValidationFailedError):
    """The source account balance cannot cover the requested amount."""


class AccountNotActiveError(ValidationFailedError):
    """The bank account involved is not in the ``Active`` state."""


class InvalidOTPError(UnauthorizedError):
    """The one-time password is missing or does not match."""


class OTPExpiredError(UnauthorizedError):
    """The one-time password has expired."""


class AccountLockedError(ForbiddenError):
    """The user account is temporarily locked after failed attempts."""


class FlaggedTransactionError(ValidationFailedError):
    """The transaction was flagged by the fraud model and awaits human review."""


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the global exception handlers to the application.

    Keeps route handlers free of try/except boilerplate: domain errors map to
    their declared status code, everything else becomes an opaque 500.
    """

    @app.exception_handler(BankAPIError)
    async def bank_api_error_handler(request: Request, exc: BankAPIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.payload()},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": {
                    "status": "error",
                    "message": "An internal error occurred. Please try again later.",
                }
            },
        )
