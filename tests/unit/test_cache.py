"""Tests for the SQLite response cache.

The cache key is sha256(model + prompt + params). Getting that key wrong is
silently catastrophic: two different prompts colliding would serve one answer for
the other, and the eval numbers would be quietly meaningless. These tests pin it.
"""

from __future__ import annotations

from src.core.cache import ResponseCache, cache_key


def test_key_is_stable_across_calls() -> None:
    a = cache_key("m", "prompt", {"temperature": 0.0})
    b = cache_key("m", "prompt", {"temperature": 0.0})
    assert a == b
    assert len(a) == 64


def test_key_is_insensitive_to_param_ordering() -> None:
    a = cache_key("m", "p", {"temperature": 0.0, "max_tokens": 10})
    b = cache_key("m", "p", {"max_tokens": 10, "temperature": 0.0})
    assert a == b


def test_key_changes_with_model_prompt_and_params() -> None:
    base = cache_key("m", "p", {"t": 1})
    assert cache_key("other", "p", {"t": 1}) != base
    assert cache_key("m", "other", {"t": 1}) != base
    assert cache_key("m", "p", {"t": 2}) != base


def test_roundtrip_miss_then_hit(tmp_path) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite")
    assert cache.get("m", "p", {}) is None
    cache.set("m", "p", {}, "the answer")
    assert cache.get("m", "p", {}) == "the answer"


def test_persists_across_instances(tmp_path) -> None:
    db = tmp_path / "c.sqlite"
    ResponseCache(db).set("m", "p", {}, "kept")
    # Survives a restart — this is what makes a re-run of the eval suite free.
    assert ResponseCache(db).get("m", "p", {}) == "kept"


def test_counts_hits_and_misses_for_the_metrics_endpoint(tmp_path) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite")
    cache.get("m", "p", {})
    cache.set("m", "p", {}, "v")
    cache.get("m", "p", {})
    cache.get("m", "p", {})
    assert cache.stats() == {"hits": 2, "misses": 1, "hit_rate": 2 / 3, "entries": 1}


def test_get_or_set_only_calls_the_producer_once(tmp_path) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite")
    calls = []

    def produce() -> str:
        calls.append(1)
        return "expensive"

    assert cache.get_or_set("m", "p", {}, produce) == "expensive"
    assert cache.get_or_set("m", "p", {}, produce) == "expensive"
    assert len(calls) == 1


def test_stores_json_values(tmp_path) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite")
    payload = {"values": [{"label": "Emberdeep", "value": 1114}]}
    cache.set_json("vlm", "plate_01", {}, payload)
    assert cache.get_json("vlm", "plate_01", {}) == payload
