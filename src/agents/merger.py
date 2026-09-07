"""A4 handoff: deduplicate and order evidence; P1 owns conflict detection."""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher

from pydantic import Field

from src.api.schemas import Conflict, Frozen, SearchHit, Warning
from src.synthesis.conflicts import MergeReport

ConflictDetector = Callable[[list[SearchHit]], list[Conflict] | MergeReport]


class Bundle(Frozen):
    chunks: list[SearchHit] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    reliability_notes: list[str] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)


def merge_evidence(
    chunks: list[SearchHit],
    *,
    hop_order: list[str] | None = None,
    detector: ConflictDetector | None = None,
) -> Bundle:
    # Different numeric assertions must survive deduplication, even in similar prose.
    kept: list[SearchHit] = []
    for chunk in sorted(chunks, key=lambda c: (c.authority_tier, -c.score)):
        if any(chunk.chunk_id == c.chunk_id or _duplicate(chunk.text, c.text) for c in kept):
            continue
        kept.append(chunk)
    if hop_order:
        ranks = {chunk_id: i for i, chunk_id in enumerate(hop_order)}
        kept.sort(key=lambda c: ranks.get(c.chunk_id, len(ranks)))
    result = Bundle(chunks=kept)
    if kept and all(c.authority_tier >= 4 for c in kept):
        result.reliability_notes.append(
            "Only partial primary records or folkloric sources were found."
        )
    if detector is None:
        result.warnings.append(
            Warning(
                type="tool_failure",
                action="conflict_detection_unavailable",
                detail="P1 conflict detector is not connected; conflict coverage is incomplete.",
            )
        )
    else:
        try:
            # Detector sees all sources, so dedup never destroys corroboration/conflicts.
            report = detector(chunks)
            conflicts = report.conflicts if isinstance(report, MergeReport) else report
            result.conflicts = [Conflict.model_validate(c) for c in conflicts]
            if isinstance(report, MergeReport):
                result.reliability_notes.extend(report.reliability_notes)
        except Exception:
            result.warnings.append(
                Warning(
                    type="tool_failure",
                    action="conflict_detection_unavailable",
                    detail="P1 conflict detection failed; conflicts are unverified.",
                )
            )
    return result


def _duplicate(left: str, right: str) -> bool:
    a, b = " ".join(left.split()), " ".join(right.split())
    if a == b:
        return True
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    # Negation changes truth; only whitespace/exact copies can merge in that case.
    if re.search(r"\b(no|not|never|none|without)\b", a + " " + b, re.I):
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.98
