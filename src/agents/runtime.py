"""Per-request budgets and the only HTTP seam used by reasoning agents."""

from __future__ import annotations

import base64
import json
import os
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from src.core.cache import ResponseCache
from src.core.llm import LLMClient, LLMResponse, Provider
from src.core.retry import RetryPolicy, call_with_retry


class CompletionClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], **params: Any) -> LLMResponse: ...


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Reserve tokens before a call; never start work after the deadline."""

    def __init__(
        self,
        max_steps: int = 6,
        max_tokens: int = 60000,
        max_wall_ms: int = 25000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.clock = clock
        self.deadline = clock() + max_wall_ms / 1000
        self.tokens = 0
        self.cancelled = False
        self.stop_reason = ""

    def remaining(self) -> float:
        remaining = self.deadline - self.clock()
        if self.cancelled or remaining <= 0:
            self.stop_reason = self.stop_reason or "wall-clock budget exhausted"
            raise BudgetExceeded(self.stop_reason)
        return remaining

    def reserve(self, tokens: int) -> None:
        self.remaining()
        if self.tokens + tokens > self.max_tokens:
            self.stop_reason = "token budget exhausted"
            self.cancelled = True
            raise BudgetExceeded(self.stop_reason)
        self.tokens += tokens

    def sleep(self, seconds: float) -> None:
        if seconds >= self.remaining():
            self.stop_reason = "retry would exceed wall-clock budget"
            raise BudgetExceeded(self.stop_reason)
        time.sleep(seconds)


class _GuardedProvider:
    def __init__(self, provider: Provider, budget: Budget) -> None:
        self.provider, self.budget = provider, budget
        self.name = provider.name

    def available(self) -> bool:
        return self.provider.available()

    def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> LLMResponse:
        params["timeout"] = min(params.get("timeout", 120), self.budget.remaining())
        # UTF-8 bytes conservatively bound input tokens, including evidence.
        self.budget.reserve(len(json.dumps(messages).encode()) + params.get("max_tokens", 800))
        return self.provider.complete(model, messages, **params)


class BoundedLLM:
    """Keep shared LLMClient caching/retry while bounding the request's wait.

    An in-flight provider request cannot be forcibly killed. On timeout its result
    is discarded, and guards prevent subsequent retries/fallback provider calls.
    Its final usage is unknown; callers emit an explicit tool-failure warning.
    Use a fresh LLMClient per request, never share the mutated provider wrappers.
    """

    def __init__(self, client: LLMClient, budget: Budget) -> None:
        self.client, self.budget = client, budget
        client.providers = [_GuardedProvider(p, budget) for p in client.providers]

    @property
    def usage(self) -> list[LLMResponse]:
        return self.client.usage

    def complete(self, messages: list[dict[str, Any]], **params: Any) -> LLMResponse:
        return _within_budget(
            lambda: self.client.complete(messages, **params),
            self.budget,
            "LLM deadline exceeded; in-flight usage unknown",
        )


def _within_budget(call: Callable[[], Any], budget: Budget, timeout_message: str) -> Any:
    timeout = budget.remaining()
    result: queue.Queue = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            result.put(call())
        except Exception as error:
            result.put(error)

    threading.Thread(target=run, daemon=True).start()
    try:
        response = result.get(timeout=timeout)
    except queue.Empty:
        budget.cancelled = True
        budget.stop_reason = timeout_message
        raise BudgetExceeded(timeout_message) from None
    if isinstance(response, Exception):
        raise response
    return response


class KnowledgeClient:
    """No imports from ingestion, graph, indexes or retrieval implementations."""

    def __init__(
        self,
        base_url: str,
        cache: ResponseCache,
        budget: Budget,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache, self.budget, self.transport = cache, budget, transport

    def request(
        self, method: str, path: str, body: dict | None = None, *, binary: bool = False
    ) -> Any:
        return _within_budget(
            lambda: self._request(method, path, body, binary=binary),
            self.budget,
            "Knowledge API deadline exceeded",
        )

    def _request(self, method: str, path: str, body: dict | None, *, binary: bool) -> Any:
        self.budget.remaining()
        url = self.base_url + path
        params = {
            "method": method,
            "body": body,
            "binary": binary,
            "revision": os.environ.get("KNOWLEDGE_REVISION", "v1"),
        }

        def fetch() -> str:
            with httpx.Client(
                transport=self.transport, timeout=min(5, self.budget.remaining())
            ) as c:
                response = c.request(method, url, json=body)
                response.raise_for_status()
                if binary:
                    return base64.b64encode(response.content).decode()
                value = response.json()
                return json.dumps(value)

        def produce() -> str:
            return call_with_retry(
                fetch,
                policy=RetryPolicy(max_attempts=5),
                sleep=self.budget.sleep,
                description="knowledge API",
            )

        raw = self.cache.get_or_set("knowledge-http-v1", url, params, produce)
        return base64.b64decode(raw) if binary else json.loads(raw)
