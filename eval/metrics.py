"""Retrieval and answer metrics, implemented from `docs/evaluation.md`.

WHY the definitions were written first: a metric authored after reading the retriever
tends to measure what the retriever already does well. The definitions in
`docs/evaluation.md` predate this file, and each function names the section it implements
so the two can be checked against each other.

WHY documents are deduplicated before scoring: two chunks from the same document are one
document found. Counting them separately would inflate recall on long documents - and the
four novels are 250 pages each, so that is not a hypothetical.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field


def _dedupe(items: Sequence[str]) -> list[str]:
    """Preserve rank order, keep the first occurrence."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# --------------------------------------------------------------------------
# Retrieval (evaluation.md section 1)
# --------------------------------------------------------------------------


def recall_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int = 10) -> float:
    """|G ∩ R@k| / |G|. Undefined with no gold, reported as 0.0."""
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    top = set(_dedupe(retrieved)[:k])
    return len(gold_set & top) / len(gold_set)


def precision_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int = 10) -> float:
    """|G ∩ R@k| / k. Bounded low by construction; diagnostic, not a target."""
    if k <= 0:
        return 0.0
    top = _dedupe(retrieved)[:k]
    return len(set(gold) & set(top)) / k


def coverage_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int = 10) -> bool:
    """G ⊆ R@k — binary per question. THE metric for sub-track 1B.

    Recall rewards finding *a* gold document. A three-document question scoring 0.67
    sounds like partial success and is a wrong answer, because the composer never sees
    the third document. Coverage refuses to award partial credit for that.
    """
    gold_set = set(gold)
    if not gold_set:
        return False
    return gold_set <= set(_dedupe(retrieved)[:k])


def ndcg_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int = 10) -> float:
    """Binary-relevance nDCG. Rank-sensitive, because the composer sees a truncated list."""
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    top = _dedupe(retrieved)[:k]
    dcg = sum(1.0 / math.log2(i + 1) for i, doc in enumerate(top, start=1) if doc in gold_set)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold_set), k) + 1))
    return dcg / ideal if ideal else 0.0


def first_relevant_rank(retrieved: Sequence[str], gold: Sequence[str], k: int = 10) -> int | None:
    """1-based rank of the first gold document, or None if absent from the top k."""
    gold_set = set(gold)
    for index, doc in enumerate(_dedupe(retrieved)[:k], start=1):
        if doc in gold_set:
            return index
    return None


def reciprocal_rank(retrieved: Sequence[str], gold: Sequence[str], k: int = 10) -> float:
    rank = first_relevant_rank(retrieved, gold, k)
    return 1.0 / rank if rank else 0.0


# --------------------------------------------------------------------------
# Answer (evaluation.md section 2)
# --------------------------------------------------------------------------


def groundedness(claims: Sequence[dict]) -> float:
    """count(support != "inferred") / count(claims).

    A refusal has zero claims and scores 0.0 rather than raising - dividing by zero on
    the one behaviour we want the system to have would be perverse.
    """
    if not claims:
        return 0.0
    grounded = sum(1 for c in claims if c.get("support") != "inferred")
    return grounded / len(claims)


def citation_precision(cited_docs: Sequence[str], gold: Sequence[str]) -> float:
    cited = _dedupe(cited_docs)
    if not cited:
        return 0.0
    return len(set(cited) & set(gold)) / len(cited)


def citation_recall(cited_docs: Sequence[str], gold: Sequence[str]) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    return len(gold_set & set(cited_docs)) / len(gold_set)


# --------------------------------------------------------------------------
# Multimodal (evaluation.md section 3)
# --------------------------------------------------------------------------


def asset_precision(returned: Sequence[str], gold: Sequence[str]) -> float:
    """Compared by asset id, which is a content hash - so the two byte-identical copies
    of each plate count once, not twice."""
    assets = _dedupe(returned)
    if not assets:
        return 0.0
    return len(set(assets) & set(gold)) / len(assets)


def asset_recall(returned: Sequence[str], gold: Sequence[str]) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    return len(gold_set & set(returned)) / len(gold_set)


def answer_matches(answer: str, accepted: Sequence[str]) -> bool:
    """Normalised containment: thousands separators, case and hyphenation ignored.

    "1,114" and "1114" are the same answer; "Thrice-Bound" and "thrice bound" are the
    same name. Anything stricter fails on formatting rather than on correctness.
    """

    def norm(value: str) -> str:
        return str(value).lower().replace(",", "").replace("-", " ").strip()

    haystack = norm(answer)
    return any(norm(a) in haystack for a in accepted if str(a).strip())


# --------------------------------------------------------------------------
# Agentic (evaluation.md section 4)
# --------------------------------------------------------------------------


def gain_per_step(steps: Sequence[dict], gold: Sequence[str]) -> list[int]:
    """New gold documents FIRST seen at each step.

    Counted against documents already seen, not per-step totals: a loop that re-retrieves
    the same gold document every step would otherwise look like it was learning.
    """
    gold_set = set(gold)
    seen: set[str] = set()
    gains: list[int] = []
    for step in steps:
        found = {d for d in step.get("documents", []) if d in gold_set}
        gains.append(len(found - seen))
        seen |= found
    return gains


def redundancy_rate(queries: Sequence[str]) -> float:
    """Fraction of issued queries that repeat an earlier one.

    Exact-match on normalised text here; the embedding-similarity version belongs with
    the agent loop, which has an embedder to hand. This is the cheap floor - a loop
    failing THIS is churning badly.
    """
    if len(queries) <= 1:
        return 0.0
    seen: set[str] = set()
    repeats = 0
    for query in queries:
        key = " ".join(query.lower().split())
        if key in seen:
            repeats += 1
        seen.add(key)
    return repeats / len(queries)


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


@dataclass
class QuestionResult:
    """One question's scores, kept per-question so failures can be inspected."""

    qid: str
    retrieved_docs: list[str] = field(default_factory=list)
    gold_docs: list[str] = field(default_factory=list)
    recall: float = 0.0
    precision: float = 0.0
    covered: bool = False
    ndcg: float = 0.0
    rr: float = 0.0
    first_rank: int | None = None
    latency_ms: int = 0
    failure: str | None = None
    note: str = ""


@dataclass
class SuiteResult:
    suite: str
    config: str
    k: int
    results: list[QuestionResult] = field(default_factory=list)

    @property
    def scored(self) -> list[QuestionResult]:
        """Questions with gold documents. A question with none cannot score retrieval,
        and averaging it in as 0.0 would understate the system rather than skip it."""
        return [r for r in self.results if r.gold_docs]

    def _mean(self, attribute: str) -> float:
        rows = self.scored
        return sum(getattr(r, attribute) for r in rows) / len(rows) if rows else 0.0

    def summary(self) -> dict[str, float | int | str]:
        rows = self.scored
        latencies = sorted(r.latency_ms for r in self.results)
        return {
            "suite": self.suite,
            "config": self.config,
            "questions": len(self.results),
            "scored": len(rows),
            f"recall@{self.k}": round(self._mean("recall"), 4),
            f"precision@{self.k}": round(self._mean("precision"), 4),
            f"coverage@{self.k}": round(
                sum(1 for r in rows if r.covered) / len(rows) if rows else 0.0, 4
            ),
            f"ndcg@{self.k}": round(self._mean("ndcg"), 4),
            "mrr": round(self._mean("rr"), 4),
            "p50_ms": latencies[len(latencies) // 2] if latencies else 0,
            "p95_ms": latencies[int(len(latencies) * 0.95)] if latencies else 0,
        }

    def failures(self) -> list[QuestionResult]:
        return [r for r in self.scored if not r.covered]
