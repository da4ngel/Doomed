"""Reciprocal Rank Fusion.

WHY RRF over score normalisation: BM25 scores are unbounded and corpus-dependent while
cosine similarity is bounded in [-1, 1]. Any attempt to put them on one scale needs
tuning that would itself have to be justified. RRF ignores the scores entirely and fuses
on rank, so there is nothing to tune and the whole thing is fifteen lines a team member
can derive on a whiteboard under questioning.

    score(d) = sum over retrievers of 1 / (k + rank(d))

k=60 is the value from the original paper and is left alone deliberately - tuning it
would be one more number to defend for a gain that does not show up at this corpus size.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RRF_K = 60


@dataclass
class FusedHit:
    chunk_id: str
    score: float
    dense_rank: int | None = None
    sparse_rank: int | None = None
    payload: dict = field(default_factory=dict)


def reciprocal_rank_fusion(
    dense: list[tuple[str, float, dict]],
    sparse: list[tuple[str, float, dict]],
    k: int = RRF_K,
    limit: int = 10,
) -> list[FusedHit]:
    """Fuse two ranked lists. Either may be empty, which is how the ablation isolates
    a single retriever without a separate code path."""
    hits: dict[str, FusedHit] = {}

    for rank, (chunk_id, _score, payload) in enumerate(dense, start=1):
        hit = hits.setdefault(chunk_id, FusedHit(chunk_id, 0.0, payload=payload))
        hit.dense_rank = rank
        hit.score += 1.0 / (k + rank)
        if not hit.payload:
            hit.payload = payload

    for rank, (chunk_id, _score, payload) in enumerate(sparse, start=1):
        hit = hits.setdefault(chunk_id, FusedHit(chunk_id, 0.0, payload=payload))
        hit.sparse_rank = rank
        hit.score += 1.0 / (k + rank)
        if not hit.payload:
            hit.payload = payload

    ordered = sorted(hits.values(), key=lambda h: (-h.score, h.chunk_id))
    return ordered[:limit]
