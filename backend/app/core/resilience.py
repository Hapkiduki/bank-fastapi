"""Lightweight async circuit breaker for outbound/unreliable dependencies.

Protects the request path from a dependency that has started failing
consistently (e.g. ML model inference): instead of paying the latency and
error cost on every call, the circuit "opens" after a run of failures and
callers fail fast until a cool-down elapses, after which a single trial call
("half-open") decides whether to close the circuit again.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, TypeVar

from backend.app.core.logging import get_logger

logger = get_logger()

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""

    def __init__(self, name: str, retry_in: float) -> None:
        super().__init__(
            f"Circuit '{name}' is open; retrying allowed in {retry_in:.1f}s"
        )
        self.name = name
        self.retry_in = retry_in


class CircuitBreaker:
    """Classic three-state circuit breaker (closed → open → half-open).

    Args:
        name: Identifier used in logs.
        failure_threshold: Consecutive failures that open the circuit.
        recovery_seconds: Cool-down before a half-open trial call is allowed.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(
        self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
    ) -> T:
        """Invoke ``func`` under the breaker's protection.

        Raises:
            CircuitOpenError: If the circuit is open and the cool-down has
                not elapsed yet.
            Exception: Whatever ``func`` raises (also recorded as a failure).
        """
        async with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._opened_at
                if elapsed < self.recovery_seconds:
                    raise CircuitOpenError(self.name, self.recovery_seconds - elapsed)
                self._state = CircuitState.HALF_OPEN
                logger.info(f"Circuit '{self.name}' half-open: allowing a trial call")

        try:
            result = await func(*args, **kwargs)
        except Exception:
            await self._record_failure()
            raise

        await self._record_success()
        return result

    async def _record_success(self) -> None:
        async with self._lock:
            if self._state != CircuitState.CLOSED:
                logger.info(f"Circuit '{self.name}' closed again after successful call")
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0

    async def _record_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1
            if (
                self._state == CircuitState.HALF_OPEN
                or self._consecutive_failures >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    f"Circuit '{self.name}' opened after "
                    f"{self._consecutive_failures} consecutive failures"
                )
