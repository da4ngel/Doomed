"""Turn an LLMResponse into a UsageRecord, and aggregate usage for /v1/metrics.

WHY this is a separate module rather than a method on LLMResponse: `LLMResponse` is the
provider layer's return type and knows nothing about which agent step it belongs to.
`UsageRecord` is the answer packet's accounting row and needs the step number and the
routing reason. Keeping the translation here stops provider concerns leaking into the
frozen schema.

WHY `routing_reason` is a required argument and not optional: the report has to answer
"why did this call use the expensive model?", and a field that can be omitted always is.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.api.schemas import UsageRecord
from src.core.llm import LLMResponse


def to_usage_record(response: LLMResponse, step: int, routing_reason: str) -> UsageRecord:
    """Translate a provider response into the packet's accounting row."""
    return UsageRecord(
        step=step,
        model=response.model,
        routing_reason=routing_reason,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        latency_ms=response.latency_ms,
        cost_usd=0.0 if response.cached else response.cost_usd,
        cache="hit" if response.cached else "miss",
        fallback_used=response.fallback_used,
    )


@dataclass
class UsageSummary:
    """Aggregate view. Feeds GET /v1/metrics and the report's cost-per-query line."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    cache_hits: int = 0
    fallbacks: int = 0

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.calls if self.calls else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_total": self.tokens_in + self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": self.latency_ms,
            "cache_hits": self.cache_hits,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "fallbacks_used": self.fallbacks,
        }


def summarise(records: list[UsageRecord]) -> UsageSummary:
    """Aggregate usage records.

    A cache hit still counts as a call: hiding it would inflate the apparent cost saving
    and make cache_hit_rate meaningless, since the denominator would shrink with it.
    """
    summary = UsageSummary()
    for record in records:
        summary.calls += 1
        summary.tokens_in += record.tokens_in
        summary.tokens_out += record.tokens_out
        summary.cost_usd += record.cost_usd
        summary.latency_ms += record.latency_ms
        summary.cache_hits += 1 if record.cache == "hit" else 0
        summary.fallbacks += 1 if record.fallback_used else 0
    return summary
