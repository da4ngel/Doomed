"""Tests for the backoff/circuit-breaker wrapper.

Written before the implementation: the challenge document warns that systems
without backoff "fail unpredictably, including during your demo recording",
so the behaviour is specified here first.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from src.core.retry import (
    CircuitBreaker,
    CircuitOpenError,
    RetryableError,
    RetryPolicy,
    call_with_retry,
)


def _sleeps() -> tuple[list[float], object]:
    recorded: list[float] = []

    def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    return recorded, fake_sleep


def test_returns_immediately_on_success() -> None:
    recorded, sleeper = _sleeps()
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    assert call_with_retry(fn, sleep=sleeper) == "ok"
    assert len(calls) == 1
    assert recorded == []


def test_backoff_is_1_2_4_8_seconds() -> None:
    recorded, sleeper = _sleeps()
    attempts = []

    def fn():
        attempts.append(1)
        if len(attempts) < 5:
            raise RetryableError("429")
        return "ok"

    policy = RetryPolicy(max_attempts=5, base_delay=1.0, jitter=0.0)
    assert call_with_retry(fn, policy=policy, sleep=sleeper) == "ok"
    assert recorded == [1.0, 2.0, 4.0, 8.0]


def _fails_once_with(status: int) -> tuple[Callable[[], str], list[int]]:
    """A callable that raises `status` on its first call, then succeeds."""
    attempts: list[int] = []

    def fn() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("GET", "https://x"),
                response=httpx.Response(status),
            )
        return "ok"

    return fn, attempts


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_http_statuses_are_retried(status: int) -> None:
    _, sleeper = _sleeps()
    fn, attempts = _fails_once_with(status)
    assert call_with_retry(fn, sleep=sleeper) == "ok"
    assert len(attempts) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(status: int) -> None:
    """A 4xx other than 429 is our bug. Retrying it only burns quota."""
    _, sleeper = _sleeps()
    fn, attempts = _fails_once_with(status)
    with pytest.raises(httpx.HTTPStatusError):
        call_with_retry(fn, sleep=sleeper)
    assert len(attempts) == 1


def test_retry_after_header_overrides_computed_backoff() -> None:
    recorded, sleeper = _sleeps()
    attempts = []

    def fn():
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.HTTPStatusError(
                "slow down",
                request=httpx.Request("GET", "https://x"),
                response=httpx.Response(429, headers={"Retry-After": "3"}),
            )
        return "ok"

    call_with_retry(fn, policy=RetryPolicy(jitter=0.0), sleep=sleeper)
    assert recorded == [3.0]


def test_raises_after_exhausting_attempts() -> None:
    _, sleeper = _sleeps()

    def always_fails():
        raise RetryableError("429")

    with pytest.raises(RetryableError):
        call_with_retry(always_fails, policy=RetryPolicy(max_attempts=3, jitter=0.0), sleep=sleeper)


def test_circuit_opens_after_threshold_and_fails_fast() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_after_s=60.0)
    _, sleeper = _sleeps()

    def always_fails():
        raise RetryableError("429")

    policy = RetryPolicy(max_attempts=1, jitter=0.0)
    for _ in range(2):
        with pytest.raises(RetryableError):
            call_with_retry(always_fails, policy=policy, breaker=breaker, sleep=sleeper)

    assert breaker.is_open
    calls = []

    def would_succeed():
        calls.append(1)
        return "ok"

    # The point of the breaker: stop hammering a dead provider mid-demo.
    with pytest.raises(CircuitOpenError):
        call_with_retry(would_succeed, breaker=breaker, sleep=sleeper)
    assert calls == []


def test_circuit_half_opens_after_cooldown() -> None:
    clock = {"t": 1000.0}
    breaker = CircuitBreaker(failure_threshold=1, reset_after_s=30.0, clock=lambda: clock["t"])
    _, sleeper = _sleeps()

    with pytest.raises(RetryableError):
        call_with_retry(
            lambda: (_ for _ in ()).throw(RetryableError("429")),
            policy=RetryPolicy(max_attempts=1, jitter=0.0),
            breaker=breaker,
            sleep=sleeper,
        )
    assert breaker.is_open

    clock["t"] += 31.0
    assert call_with_retry(lambda: "ok", breaker=breaker, sleep=sleeper) == "ok"
    assert not breaker.is_open
