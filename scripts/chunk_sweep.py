"""Ablation row 9 — chunk size 300 / 450 / 600, measured rather than argued.

ADR-008 moved the target from 600 to 450 on a *defect* argument: at 600, 173 chunks
(8.8%) exceeded BGE-small's 512-token context and were indexed but only partly embedded —
present in the store, unreachable by dense retrieval, with nothing logged. That justifies
leaving 600. It has never established that 450 beats 300, and the ablation table has
carried row 9 as "not run" ever since.

**This script never touches the working index.** Each size builds into its own
`index_dir` and its own Qdrant collection (`ashen_sweep_<n>`), so a sweep that dies
half-way costs nothing but time. The production collection is named in
`Settings.qdrant_collection`, which exists for exactly this reason.

Cost is real: each size re-embeds the whole corpus at roughly 1.6 chunks/sec, so budget
~25 minutes per size. `--sizes 300` runs one.

Blocks and documents are reused as-is — chunking is the only variable, which is the whole
point of the row. Copying them into the sweep directory rather than re-running ingestion
keeps the comparison clean and the run short.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from src.core.config import Settings, get_settings

SUITES = ("multihop_1b", "rich_1a", "paraphrase")
SIZES = (300, 450, 600)


def sweep_settings(size: int, root: Path) -> Settings:
    """A Settings pointing entirely at this size's own directory and collection."""
    base = get_settings()
    return base.model_copy(
        update={
            "index_dir": root / f"chunk_{size}",
            "qdrant_collection": f"ashen_sweep_{size}",
            "qdrant_path": root / f"chunk_{size}" / "qdrant",
        }
    )


def prepare(size: int, root: Path) -> Settings:
    settings = sweep_settings(size, root)
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    source = get_settings().index_dir
    for name in ("documents.jsonl", "blocks.jsonl", "images.jsonl"):
        target = settings.index_dir / name
        if not target.exists() and (source / name).exists():
            shutil.copy2(source / name, target)
    return settings


def build_one(size: int, settings: Settings, parallel: int) -> dict:
    """Chunk, embed and index one size. Returns what it produced, counted."""
    from src.indexing.bm25_store import BM25Store, load_chunks
    from src.indexing.embed import get_embedder
    from src.indexing.qdrant_store import QdrantStore
    from src.ingestion import chunker

    print(f"\n=== chunk target {size} ===", flush=True)
    chunker.run(settings, target_tokens=size)
    chunks = load_chunks(settings)
    print(f"  chunks          {len(chunks)}", flush=True)

    over = sum(1 for c in chunks if c.token_count > chunker.EMBED_CONTEXT_TOKENS)
    print(f"  over 512 tokens {over} ({over / max(len(chunks), 1):.1%})", flush=True)

    sparse = BM25Store(settings)
    sparse.build(chunks)

    embedder = get_embedder(settings)
    store = QdrantStore(settings, embedder.dimensions)
    store.recreate()

    started = time.perf_counter()
    for start in range(0, len(chunks), 256):
        batch = chunks[start : start + 256]
        vectors = embedder.embed_documents([c.text for c in batch], parallel=parallel)
        store.upsert(batch, vectors)
        print(f"    embedded {min(start + 256, len(chunks))}/{len(chunks)}", flush=True)

    indexed = store.count()
    store.close()

    # Assert rather than log. Three separate indexing bugs in this project printed a
    # success line while being wrong, and a sweep row built on a short index would look
    # like a chunk-size finding.
    if indexed != len(chunks):
        raise RuntimeError(f"size {size}: indexed {indexed} of {len(chunks)} chunks")

    return {
        "size": size,
        "chunks": len(chunks),
        "over_context": over,
        "median_tokens": sorted(c.token_count for c in chunks)[len(chunks) // 2],
        "embed_seconds": round(time.perf_counter() - started, 1),
    }


def score_one(settings: Settings, suites: tuple[str, ...]) -> dict:
    from eval.runner import Config, run_suite
    from src.retrieval.hybrid import Retriever

    configs = [
        Config("3. Hybrid RRF"),
        Config("6. + graph expand", expand=True, expand_mode="graph"),
    ]
    retriever = Retriever(settings=settings)
    scores: dict[str, dict] = {}
    for suite in suites:
        for config in configs:
            result = run_suite(suite, config, 10, retriever)
            scores[f"{suite} | {config.name}"] = result.summary()
    retriever.vectors.close()
    return scores


def print_table(rows: list[dict], scores: dict[int, dict], suites: tuple[str, ...]) -> None:
    print("\n\n=== chunk size sweep ===\n")
    header = f"{'size':>5} {'chunks':>7} {'>512':>6} {'embed s':>8}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['size']:>5} {row['chunks']:>7} {row['over_context']:>6} "
            f"{row['embed_seconds']:>8.0f}"
        )

    for suite in suites:
        print(f"\n{suite}")
        head = f"  {'size':>5} {'config':22s} {'recall@10':>9} {'cov@10':>7} {'ndcg':>6}"
        print(head)
        print("  " + "-" * (len(head) - 2))
        for size in sorted(scores):
            for key, summary in scores[size].items():
                if not key.startswith(suite):
                    continue
                config = key.split(" | ", 1)[1]
                print(
                    f"  {size:>5} {config:22s} {summary['recall@10']:9.3f} "
                    f"{summary['coverage@10']:7.3f} {summary['ndcg@10']:6.3f}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    parser.add_argument("--suites", nargs="+", default=list(SUITES))
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--root", default="data/sweep")
    parser.add_argument("--out", default="docs/reports/chunk-sweep.json")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the sweep indexes instead of deleting them afterwards",
    )
    args = parser.parse_args()

    root = Path(args.root)
    rows: list[dict] = []
    scores: dict[int, dict] = {}

    for size in args.sizes:
        settings = prepare(size, root)
        rows.append(build_one(size, settings, args.parallel))
        scores[size] = score_one(settings, tuple(args.suites))

    print_table(rows, scores, tuple(args.suites))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"builds": rows, "scores": {str(k): v for k, v in scores.items()}}, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")

    if not args.keep:
        # The sweep indexes are ~4x the working index on disk and serve no further
        # purpose; the numbers are in the JSON.
        from src.indexing.qdrant_store import QdrantStore

        for size in args.sizes:
            settings = sweep_settings(size, root)
            try:
                store = QdrantStore(settings)
                client = store.client()
                if client.collection_exists(store.collection):
                    client.delete_collection(store.collection)
                store.close()
            except Exception as exc:  # noqa: BLE001 - cleanup must not fail the run
                print(f"  could not drop ashen_sweep_{size}: {exc}")
        shutil.rmtree(root, ignore_errors=True)
        print("dropped sweep indexes (--keep to retain them)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
