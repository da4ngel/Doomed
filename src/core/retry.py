"""Exponential backoff and a circuit breaker for every outbound call.

WHY: the free tiers this project runs on return HTTP 429 under load, and the
challenge document is explicit that systems without backoff "fail unpredictably,
including during your demo recording". CLAUDE.md therefore makes this module
mandatory on every external call — there is no sanctioned path around it.

The breaker exists for a different failure than the retries do. Retries handle a
provider that is briefly busy; the breaker handles a provider that is *down*, where
continuing to retry burns the wall-clock budget of every subsequent query. Failing
fast lets the caller fall back to another provider while the demo is still running.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

import httpx

log = logging.getLogger(__name__)

T = TypeVar("T")

#: Status codes worth retrying. A 4xx other than 429 is our bug, and retrying it
#: only burns quota against a request that will never succeed.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class RetryableError(Exception):
    """Raised by callers to force a retry for a non-HTTP transient fault."""


class CircuitOpenError(Exception):
    """The breaker is open; the call was not attempted."""


@dataclass(frozen=True)
class RetryPolicy:
    """Backoff schedule. Defaults give the 1s/2s/4s/8s sequence the plan specifies."""

    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: float = 0.25

    def delay_for(self, attempt: int) -> float:
        """Delay before retry number `attempt` (1-based)."""
        raw = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        if self.jitter:
            raw += random.uniform(0, self.jitter * raw)
        return raw


@dataclass
class CircuitBreaker:
    """Trips after `failure_threshold` consecutive failures, closes after a cooldown."""

    failure_threshold: int = 5
    reset_after_s: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if self.clock() - self._opened_at >= self.reset_after_s:
            # Half-open: allow one probe through rather than staying dark forever.
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = self.clock()
            log.warning("circuit opened after %d consecutive failures", self._failures)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError))


def _retry_after(exc: BaseException) -> float | None:
    """Honour a server-supplied Retry-After; the provider knows better than we do."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    raw = exc.response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def call_with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    breaker: CircuitBreaker | None = None,
    sleep: Callable[[float], None] = time.sleep,
    description: str = "call",
) -> T:
    """Run `fn`, retrying transient failures with exponential backoff.

    `sleep` is injected so tests assert the schedule without waiting 15 seconds.
    """
    policy = policy or RetryPolicy()
    if breaker is not None and breaker.is_open:
        raise CircuitOpenError(f"{description}: circuit open, not attempted")

    last: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below unless retryable
            last = exc
            if not _is_retryable(exc):
                # Deliberately does NOT trip the breaker. A 404 for a retired model id
                # or a 400 for a malformed body is *our* bug, not the provider being
                # unhealthy, and tripping on it makes the breaker block every later
                # call to a provider that is actually fine. That is exactly how a
                # stale model id took out a whole escalation ladder.
                raise
            if attempt == policy.max_attempts:
                break
            delay = _retry_after(exc)
            if delay is None:
                delay = policy.delay_for(attempt)
            log.info(
                "%s failed (attempt %d/%d): %s - retrying in %.2fs",
                description,
                attempt,
                policy.max_attempts,
                type(exc).__name__,
                delay,
            )
            sleep(delay)
        else:
            if breaker is not None:
                breaker.record_success()
            return result

    if breaker is not None:
        breaker.record_failure()
    assert last is not None
    raise last
