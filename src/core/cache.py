"""SQLite response cache keyed on sha256(model + prompt + params).

WHY: two separate problems, one solution.

1. Cost and time. Re-running the eval suite must be near-free, otherwise the
   ablation table — the single highest-leverage page in the submission — becomes
   something we can only afford to produce once, and therefore cannot iterate on.
2. Demo safety. A cached answer cannot be rate-limited. Warming the cache before
   recording is what stops a 429 from ending a take.

The key includes the params because a temperature change is a different call. It
is a *content* hash, not an identity hash, so a cache built on one machine stays
valid on another — which is what makes the judge's clean-clone run fast too.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key        TEXT PRIMARY KEY,
    model      TEXT NOT NULL,
    value      TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec'))
);

-- Hit/miss totals live in the DATABASE, not on the instance. The knowledge API and the
-- reasoning service are separate processes and the LLM calls happen in the latter, so an
-- in-process counter read by GET /v1/metrics in the former is structurally always zero.
CREATE TABLE IF NOT EXISTS counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""


def cache_key(model: str, prompt: str, params: Mapping[str, Any] | None = None) -> str:
    """Content hash of a call. `sort_keys` makes it order-insensitive."""
    canonical = json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256()
    digest.update(model.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(prompt.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(canonical.encode("utf-8"))
    return digest.hexdigest()


class ResponseCache:
    """Process-safe cache over one SQLite file."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _bump(self, name: str) -> None:
        """Increment a durable counter. Never let bookkeeping break a cache read."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO counters (name, value) VALUES (?, 1) "
                    "ON CONFLICT(name) DO UPDATE SET value = value + 1",
                    (name,),
                )
        except sqlite3.Error:  # noqa: BLE001 - a metric must never fail a lookup
            pass

    def get(self, model: str, prompt: str, params: Mapping[str, Any] | None = None) -> str | None:
        key = cache_key(model, prompt, params)
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM responses WHERE key = ?", (key,)).fetchone()
        if row is None:
            self._misses += 1
            self._bump("misses")
            return None
        self._hits += 1
        self._bump("hits")
        return str(row[0])

    def set(self, model: str, prompt: str, params: Mapping[str, Any] | None, value: str) -> None:
        key = cache_key(model, prompt, params)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO responses (key, model, value) VALUES (?, ?, ?)",
                (key, model, value),
            )

    def get_or_set(
        self,
        model: str,
        prompt: str,
        params: Mapping[str, Any] | None,
        produce: Callable[[], str],
    ) -> str:
        """Return the cached value, or call `produce` once and store the result."""
        cached = self.get(model, prompt, params)
        if cached is not None:
            return cached
        value = produce()
        self.set(model, prompt, params, value)
        return value

    def get_json(
        self, model: str, prompt: str, params: Mapping[str, Any] | None = None
    ) -> Any | None:
        raw = self.get(model, prompt, params)
        return None if raw is None else json.loads(raw)

    def set_json(
        self, model: str, prompt: str, params: Mapping[str, Any] | None, value: Any
    ) -> None:
        self.set(model, prompt, params, json.dumps(value, ensure_ascii=False))

    def stats(self) -> dict[str, float | int]:
        """Feeds `cache_hit_rate` on GET /v1/metrics."""
        with self._lock, self._connect() as conn:
            entries = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
            counted = dict(conn.execute("SELECT name, value FROM counters").fetchall())
        hits = int(counted.get("hits", 0))
        misses = int(counted.get("misses", 0))
        total = hits + misses
        return {
            "hits": hits,
            "misses": misses,
            "hit_rate": (hits / total) if total else 0.0,
            "entries": int(entries),
        }
