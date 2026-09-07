"""Tests for the eval regression gate.

The gate's only job is to fail when a number falls. These tests pin the boundary in
both directions, because a gate that never fires and a gate that fires constantly are
equally useless - the second one gets deleted the week before the deadline.
"""

from __future__ import annotations

from eval.runner import GATE_TOLERANCE, compare_to_baseline


def _row(config: str = "3. Hybrid RRF", **metrics) -> dict:
    base = {
        "suite": "multihop_1b",
        "config": config,
        "questions": 7,
        "scored": 7,
        "recall@10": 0.714,
        "coverage@10": 0.429,
        "ndcg@10": 0.590,
        "mrr": 0.762,
        "p50_ms": 120,
        "p95_ms": 144,
    }
    return {**base, **metrics}


def _payload(*rows: dict) -> dict:
    return {"multihop_1b": list(rows)}


def test_an_unchanged_run_passes_clean() -> None:
    payload = _payload(_row())
    regressions, improvements = compare_to_baseline(payload, _payload(_row()))
    assert regressions == []
    assert improvements == []


def test_a_dropped_metric_is_a_regression() -> None:
    payload = _payload(_row(**{"coverage@10": 0.143}))
    regressions, _ = compare_to_baseline(payload, _payload(_row()))
    assert len(regressions) == 1
    assert "coverage@10" in regressions[0]
    assert "0.429 -> 0.143" in regressions[0]


def test_a_gain_is_reported_not_failed() -> None:
    """A gain is the moment to re-record the baseline, so the gate has to say so."""
    payload = _payload(_row(**{"recall@10": 0.857}))
    regressions, improvements = compare_to_baseline(payload, _payload(_row()))
    assert regressions == []
    assert len(improvements) == 1
    assert "+0.143" in improvements[0]


def test_movement_within_tolerance_is_ignored() -> None:
    payload = _payload(_row(**{"ndcg@10": 0.590 - GATE_TOLERANCE / 2}))
    regressions, improvements = compare_to_baseline(payload, _payload(_row()))
    assert regressions == []
    assert improvements == []


def test_latency_is_not_gated() -> None:
    """Latency is a property of the machine, not of the retriever. Gating it would fail
    the build on a busy laptop and teach people to pass --no-gate."""
    payload = _payload(_row(p95_ms=9999, p50_ms=9999))
    regressions, improvements = compare_to_baseline(payload, _payload(_row()))
    assert regressions == []
    assert improvements == []


def test_a_config_absent_from_the_baseline_fails_loudly() -> None:
    """Silently passing an unrecorded config is how a gate ends up covering nothing."""
    payload = _payload(_row(config="5. Hybrid + graph"))
    regressions, _ = compare_to_baseline(payload, _payload(_row()))
    assert len(regressions) == 1
    assert "not in baseline" in regressions[0]


def test_a_suite_absent_from_the_baseline_fails_loudly() -> None:
    payload = {"brand_new_suite": [_row()]}
    regressions, _ = compare_to_baseline(payload, _payload(_row()))
    assert len(regressions) == 1
    assert "not in baseline" in regressions[0]


def test_every_config_in_a_suite_is_checked() -> None:
    payload = _payload(
        _row(config="1. BM25 only", **{"recall@10": 0.100}),
        _row(config="3. Hybrid RRF", **{"mrr": 0.100}),
    )
    baseline = _payload(_row(config="1. BM25 only"), _row(config="3. Hybrid RRF"))
    regressions, _ = compare_to_baseline(payload, baseline)
    assert len(regressions) == 2
