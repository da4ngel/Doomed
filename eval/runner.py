"""Run a gold suite against a retrieval configuration and score it.

WHY the configs are data and not code paths: the ablation table is nine rows of the same
`Retriever.search`, differing only in a request. If "+rerank" needed its own
implementation, that row would measure two changes at once and the number would mean
nothing.

WHY every stage asserts its counts: three separate indexing bugs in this project printed
a success line while being wrong - 2,441 chunks indexed as 256 vectors, filters matching
nothing, chunks embedded past the model's context. A harness that only logs is how those
survive into a report.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from eval.metrics import (
    QuestionResult,
    SuiteResult,
    coverage_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from src.api.schemas import SearchFilters, SearchRequest

SUITES = Path(__file__).resolve().parent / "suites"


@dataclass(frozen=True)
class Config:
    """One ablation row. Data, not a code path."""

    name: str
    mode: str = "hybrid"
    rerank: bool = False
    k: int = 10

    def request(self, query: str, k: int) -> SearchRequest:
        return SearchRequest(
            query=query, mode=self.mode, k=k, rerank=self.rerank, filters=SearchFilters()
        )


#: The retrieval rows of the ablation table. Rows 5-9 need the graph expansion, the agent
#: loop and the conflict layer, which land later; they are absent rather than faked.
ABLATION: list[Config] = [
    Config("1. BM25 only", mode="sparse", rerank=False),
    Config("2. Dense only", mode="dense", rerank=False),
    Config("3. Hybrid RRF", mode="hybrid", rerank=False),
    Config("4. Hybrid + rerank", mode="hybrid", rerank=True),
]


def load_suite(name: str) -> dict:
    path = SUITES / f"{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in SUITES.glob("*.json"))
        raise FileNotFoundError(f"no suite {name!r}; have {available}")
    return json.loads(path.read_text(encoding="utf-8"))


def gold_documents(question: dict) -> list[str]:
    """Gold documents for a question, whatever suite shape it came from.

    1A labels carry `gold_assets` as corpus paths, and an image chunk's `doc_id` IS its
    canonical path - so the two line up without a translation table.
    """
    gold = list(question.get("gold_docs") or [])
    gold += list(question.get("gold_assets") or [])
    return gold


class EmptyIndexError(RuntimeError):
    """The index a config needs is empty. Refusing to score is the whole point."""


def assert_index_ready(config: Config, retriever) -> None:
    """Fail loudly rather than score an empty index as 0.000.

    Dense retrieval scoring 0.000 on all 20 questions is not a weak result, it is a
    broken one - and an empty Qdrant collection returns [] rather than raising, so the
    whole ablation ran to completion and produced a table of zeros. Switching between
    the embedded store and the Docker service is exactly when this happens, because the
    vectors live in whichever store was written and do not transfer.
    """
    if config.mode in {"dense", "hybrid"}:
        vectors = retriever.vectors.count()
        if vectors == 0:
            raise EmptyIndexError(
                f"config {config.name!r} needs dense vectors and the "
                f"{retriever.vectors.mode} Qdrant store holds 0. "
                "Run `uv run python -m src.indexing.build` against the store named by "
                "QDRANT_URL / QDRANT_PATH."
            )
    if config.mode in {"sparse", "hybrid"} and retriever.sparse.size == 0:
        raise EmptyIndexError(
            f"config {config.name!r} needs BM25 and the index is empty. "
            "Run `uv run python -m src.indexing.build`."
        )


def run_suite(suite_name: str, config: Config, k: int = 10, retriever=None) -> SuiteResult:
    from src.retrieval.hybrid import Retriever

    suite = load_suite(suite_name)
    questions = suite["questions"]
    retriever = retriever or Retriever()
    assert_index_ready(config, retriever)

    result = SuiteResult(suite=suite_name, config=config.name, k=k)
    for question in questions:
        gold = gold_documents(question)
        started = time.perf_counter()
        response = retriever.search(config.request(question["question"], k))
        latency = int((time.perf_counter() - started) * 1000)

        retrieved = [hit.doc_id for hit in response.hits]
        result.results.append(
            QuestionResult(
                qid=question["qid"],
                retrieved_docs=retrieved,
                gold_docs=gold,
                recall=recall_at_k(retrieved, gold, k),
                precision=precision_at_k(retrieved, gold, k),
                covered=coverage_at_k(retrieved, gold, k),
                ndcg=ndcg_at_k(retrieved, gold, k),
                rr=reciprocal_rank(retrieved, gold, k),
                first_rank=None,
                latency_ms=latency,
                note=question.get("trap", "")[:80],
            )
        )
    return result


def print_table(rows: list[SuiteResult]) -> None:
    if not rows:
        return
    k = rows[0].k
    header = (
        f"{'config':22s} {'n':>3s} {'recall@' + str(k):>9s} "
        f"{'cov@' + str(k):>7s} {'ndcg':>6s} {'mrr':>6s} {'p95ms':>6s}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        s = row.summary()
        print(
            f"{row.config:22s} {s['scored']:3d} {s[f'recall@{k}']:9.3f} "
            f"{s[f'coverage@{k}']:7.3f} {s[f'ndcg@{k}']:6.3f} {s['mrr']:6.3f} {s['p95_ms']:6d}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="all", help="suite name, or 'all'")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--ablation", action="store_true", help="run every config")
    parser.add_argument("--config", default="4. Hybrid + rerank")
    parser.add_argument("--failures", action="store_true", help="list uncovered questions")
    parser.add_argument("--out", help="write JSON results here")
    args = parser.parse_args()

    suites = (
        [s.stem for s in sorted(SUITES.glob("*.json")) if s.stem != "chart_reading"]
        if args.suite == "all"
        else [args.suite]
    )
    configs = ABLATION if args.ablation else [c for c in ABLATION if c.name == args.config]
    if not configs:
        print(f"unknown config {args.config!r}; have {[c.name for c in ABLATION]}")
        return 2

    from src.retrieval.hybrid import Retriever

    retriever = Retriever()
    payload: dict[str, list[dict]] = {}

    for suite_name in suites:
        print(f"\n=== {suite_name} (k={args.k}) ===")
        rows = [run_suite(suite_name, c, args.k, retriever) for c in configs]
        print_table(rows)
        payload[suite_name] = [r.summary() for r in rows]

        if args.failures:
            for row in rows:
                misses = row.failures()
                if misses:
                    print(f"\n  uncovered under {row.config}:")
                    for miss in misses:
                        found = len(set(miss.gold_docs) & set(miss.retrieved_docs))
                        print(
                            f"    {miss.qid:8s} {found}/{len(miss.gold_docs)} gold docs"
                            f"{'  | ' + miss.note if miss.note else ''}"
                        )

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")

    retriever.vectors.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
