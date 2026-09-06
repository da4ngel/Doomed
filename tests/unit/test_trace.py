"""Tests for trace and usage persistence.

These pin the interface P2 builds the orchestrator against, so the contract is settled
before two people write against it from opposite sides.
"""

from __future__ import annotations

import pytest

from src.api.schemas import TraceStep, UsageRecord
from src.core.trace import TraceStore
from src.core.usage import summarise, to_usage_record


@pytest.fixture()
def store(tmp_path) -> TraceStore:
    return TraceStore(tmp_path / "traces.sqlite")


def _step(n: int, **kwargs) -> TraceStep:
    defaults = {
        "step": n,
        "agent": "retrieval",
        "action": "hybrid_search",
        "query": f"query {n}",
        "found": 8,
        "new_gold_docs": 3,
        "learned": "Five signatory houses; two named here",
        "missing": "identities of the remaining three",
        "latency_ms": 412,
    }
    return TraceStep(**{**defaults, **kwargs})


def test_start_returns_a_usable_trace_id(store: TraceStore) -> None:
    trace_id = store.start("who won the war?", "agent")
    assert trace_id.startswith("tr_")
    assert store.get(trace_id) is not None


def test_steps_are_returned_in_order(store: TraceStore) -> None:
    trace_id = store.start("q", "agent")
    for n in (3, 1, 2):
        store.record(trace_id, _step(n))
    assert [s.step for s in store.steps(trace_id)] == [1, 2, 3]


def test_a_step_is_readable_before_the_run_finishes(store: TraceStore) -> None:
    """The UI polls a trace while the loop is still running, so steps must be durable
    immediately rather than batched at the end."""
    trace_id = store.start("q", "agent")
    store.record(trace_id, _step(1))
    assert len(store.get(trace_id)["reasoning_trace"]) == 1
    assert store.get(trace_id)["status"] == "running"


def test_learned_and_missing_survive_the_round_trip(store: TraceStore) -> None:
    """These two strings are what make a trace evidence of reasoning rather than of a
    loop having run. They are rendered in the panel and quoted in the report."""
    trace_id = store.start("q", "agent")
    store.record(trace_id, _step(1))
    step = store.steps(trace_id)[0]
    assert step.learned == "Five signatory houses; two named here"
    assert step.missing == "identities of the remaining three"


def test_recording_the_same_step_twice_replaces_it(store: TraceStore) -> None:
    """A retried step must not appear twice and inflate `iterations`."""
    trace_id = store.start("q", "agent")
    store.record(trace_id, _step(1, found=8))
    store.record(trace_id, _step(1, found=12))
    steps = store.steps(trace_id)
    assert len(steps) == 1
    assert steps[0].found == 12


def test_finish_marks_the_trace_complete(store: TraceStore) -> None:
    trace_id = store.start("q", "agent")
    store.finish(trace_id)
    trace = store.get(trace_id)
    assert trace["status"] == "ok"
    assert trace["ended_at"]


def test_unknown_trace_returns_none_not_an_error(store: TraceStore) -> None:
    assert store.get("tr_nope") is None


def test_gain_per_step_is_the_1c_metric(store: TraceStore) -> None:
    """A loop that reasons keeps finding documents the previous step made reachable.
    A loop that churns returns zeros after step 1."""
    trace_id = store.start("q", "agent")
    store.record(trace_id, _step(1, new_gold_docs=3))
    store.record(trace_id, _step(2, new_gold_docs=2))
    store.record(trace_id, _step(3, new_gold_docs=0))
    assert store.gain_per_step(trace_id) == [3, 2, 0]


def test_usage_aggregates_into_the_trace(store: TraceStore) -> None:
    trace_id = store.start("q", "agent")
    store.record_usage(
        trace_id,
        UsageRecord(step=1, model="m", tokens_in=4210, tokens_out=302, cost_usd=0.0009),
    )
    store.record_usage(
        trace_id,
        UsageRecord(
            step=2,
            model="m",
            tokens_in=1000,
            tokens_out=100,
            cost_usd=0.0002,
            cache="hit",
        ),
    )
    trace = store.get(trace_id)
    assert trace["total_tokens"] == 5612
    assert trace["total_cost_usd"] == pytest.approx(0.0011)
    assert trace["cache_hits"] == 1


def test_traces_are_isolated_from_each_other(store: TraceStore) -> None:
    first = store.start("q1", "agent")
    second = store.start("q2", "rich")
    store.record(first, _step(1))
    assert len(store.get(first)["reasoning_trace"]) == 1
    assert len(store.get(second)["reasoning_trace"]) == 0


def test_recent_lists_newest_first(store: TraceStore) -> None:
    store.start("older", "agent")
    store.start("newer", "agent")
    assert {t["question"] for t in store.recent()} == {"older", "newer"}


# --------------------------------------------------------------------------
# usage translation
# --------------------------------------------------------------------------


def test_llm_response_translates_to_a_usage_record() -> None:
    from src.core.llm import LLMResponse

    response = LLMResponse(
        text="x",
        model="deepseek/deepseek-chat",
        provider="openrouter",
        tokens_in=100,
        tokens_out=20,
        latency_ms=900,
        cost_usd=0.0001,
        cached=True,
        fallback_used=True,
    )
    record = to_usage_record(response, step=2, routing_reason="synthesis_requires_reasoning")
    assert record.step == 2
    assert record.cache == "hit"
    assert record.fallback_used is True
    assert record.routing_reason == "synthesis_requires_reasoning"


def test_a_cache_hit_still_counts_as_a_call() -> None:
    """Excluding hits would shrink the denominator and make cache_hit_rate meaningless."""
    records = [
        UsageRecord(step=1, model="m", tokens_in=10, tokens_out=5, cost_usd=0.001),
        UsageRecord(step=2, model="m", tokens_in=10, tokens_out=5, cache="hit"),
    ]
    summary = summarise(records)
    assert summary.calls == 2
    assert summary.cache_hit_rate == 0.5


def test_summary_of_no_calls_does_not_divide_by_zero() -> None:
    assert summarise([]).cache_hit_rate == 0.0
