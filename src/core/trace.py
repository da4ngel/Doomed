"""Reasoning trace persistence — every agent step, recorded as it happens.

WHY this exists as its own store rather than a field on an in-memory object: the trace is
the evidence that sub-track 1C works. `GET /v1/traces/{id}` has to return the trajectory
after the request has finished, the UI panel reads it while the loop is still running, and
the report quotes a real trajectory from an actual run. None of that survives in process
memory.

WHY P1 wrote the interface and P2 fills in the behaviour: `AnswerPacket.reasoning_trace`
and `.usage` are in the frozen schema and the orchestrator writes to them on every step,
so both builders would otherwise create this file independently and collide. The shape is
fixed here; the orchestrator that drives it belongs to P2.

WHAT MAKES A TRACE WORTH READING: `learned` and `missing` on each step. A trace that only
records "searched, found 8" proves a loop ran. A trace that records "found five signatory
houses, two named here" then "identities of the remaining three" proves the loop
*reasoned*, and that is the distinction the whole sub-track rests on.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from src.api.schemas import TraceStep, UsageRecord
from src.core.config import Settings, get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id   TEXT PRIMARY KEY,
    question   TEXT NOT NULL,
    mode       TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    status     TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS trace_steps (
    trace_id TEXT NOT NULL,
    step     INTEGER NOT NULL,
    payload  TEXT NOT NULL,
    PRIMARY KEY (trace_id, step)
);

CREATE TABLE IF NOT EXISTS trace_usage (
    trace_id TEXT NOT NULL,
    seq      INTEGER NOT NULL,
    payload  TEXT NOT NULL,
    PRIMARY KEY (trace_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_steps_trace ON trace_steps(trace_id);
CREATE INDEX IF NOT EXISTS idx_usage_trace ON trace_usage(trace_id);
"""


def new_trace_id() -> str:
    """Short, sortable-ish, and safe in a URL path."""
    return f"tr_{uuid.uuid4().hex[:16]}"


class TraceStore:
    """SQLite-backed store for reasoning traces and usage records."""

    def __init__(self, db_path: str | Path | None = None, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self.db_path = Path(db_path or settings.trace_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    # -- writing ---------------------------------------------------------

    def start(self, question: str, mode: str) -> str:
        """Open a trace and return its id. Call before the first agent runs."""
        trace_id = new_trace_id()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO traces (trace_id, question, mode, started_at) VALUES (?, ?, ?, ?)",
                (trace_id, question, mode, datetime.now(UTC).isoformat(timespec="seconds")),
            )
        return trace_id

    def record(self, trace_id: str, step: TraceStep) -> None:
        """Append one agent step.

        Written immediately rather than batched at the end, so the UI can poll a trace
        while the loop is still running - a trace panel that only fills in after the
        answer arrives shows nothing worth watching.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO trace_steps (trace_id, step, payload) VALUES (?, ?, ?)",
                (trace_id, step.step, step.model_dump_json()),
            )

    def record_usage(self, trace_id: str, usage: UsageRecord) -> None:
        """Append one model call's cost and latency."""
        with self._connect() as conn:
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM trace_usage WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO trace_usage (trace_id, seq, payload) VALUES (?, ?, ?)",
                (trace_id, int(seq), usage.model_dump_json()),
            )

    def finish(self, trace_id: str, status: str = "ok") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE traces SET ended_at = ?, status = ? WHERE trace_id = ?",
                (datetime.now(UTC).isoformat(timespec="seconds"), status, trace_id),
            )

    # -- reading ---------------------------------------------------------

    def steps(self, trace_id: str) -> list[TraceStep]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM trace_steps WHERE trace_id = ? ORDER BY step", (trace_id,)
            ).fetchall()
        return [TraceStep(**json.loads(r["payload"])) for r in rows]

    def usage(self, trace_id: str) -> list[UsageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM trace_usage WHERE trace_id = ? ORDER BY seq", (trace_id,)
            ).fetchall()
        return [UsageRecord(**json.loads(r["payload"])) for r in rows]

    def get(self, trace_id: str) -> dict | None:
        """Full trajectory, as served by GET /v1/traces/{id}."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
        if row is None:
            return None

        steps = self.steps(trace_id)
        usage = self.usage(trace_id)
        return {
            "trace_id": trace_id,
            "question": row["question"],
            "mode": row["mode"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "iterations": len(steps),
            "reasoning_trace": [s.model_dump() for s in steps],
            "usage": [u.model_dump() for u in usage],
            "total_cost_usd": round(sum(u.cost_usd for u in usage), 6),
            "total_tokens": sum(u.tokens_in + u.tokens_out for u in usage),
            "cache_hits": sum(1 for u in usage if u.cache == "hit"),
        }

    def recent(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT trace_id, question, mode, status, started_at FROM traces "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def gain_per_step(self, trace_id: str) -> list[int]:
        """New gold documents found at each step - the 1C metric.

        A loop that churns returns zeros after step 1. A loop that reasons keeps finding
        documents it could not have reached without what the previous step taught it.
        """
        return [s.new_gold_docs for s in self.steps(trace_id)]
