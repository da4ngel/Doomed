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


def test_hit_rate_survives_a_new_instance(tmp_path) -> None:
    """GET /v1/metrics builds a fresh ResponseCache on every call, so an in-process
    counter made `cache_hit_rate` unconditionally 0.0 - a reported, load-bearing
    metric that was always wrong.

    It is worse than a stale number here: the knowledge API serves /v1/metrics and the
    reasoning service makes the LLM calls, and they are SEPARATE PROCESSES. An
    in-memory counter could never have been right no matter how it was read.
    """
    db = tmp_path / "cache.sqlite"
    cache = ResponseCache(db)

    assert cache.get("m", "p", {}) is None  # miss
    cache.set("m", "p", {}, "v")
    assert cache.get("m", "p", {}) == "v"  # hit

    reader = ResponseCache(db)  # stands in for the other process
    stats = reader.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5
    assert stats["entries"] == 1


def test_a_counter_failure_never_breaks_a_cache_read(tmp_path) -> None:
    """Bookkeeping is not worth failing a lookup for.

    Exercised by pointing the counter write at an unopenable path, rather than by
    replacing _bump - replacing the method would also replace the try/except that is
    the thing under test.
    """
    cache = ResponseCache(tmp_path / "cache.sqlite")
    cache.set("m", "p", {}, "v")

    cache.db_path = tmp_path  # a directory: sqlite cannot open it
    cache._bump("hits")  # must not raise

    cache.db_path = tmp_path / "cache.sqlite"
    assert cache.get("m", "p", {}) == "v", "the value must still come back"
