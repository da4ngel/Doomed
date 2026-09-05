"""Build the dense and sparse indexes from chunks.jsonl.

Both indexes are built in one pass over the same chunk list, in the same order, so a
chunk_id means the same thing in both. Fusion depends on that.
"""

from __future__ import annotations

import argparse
import sys
import time

from src.core.config import get_settings
from src.indexing.bm25_store import BM25Store, load_chunks
from src.indexing.embed import get_embedder
from src.indexing.qdrant_store import QdrantStore, QdrantUnavailableError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--parallel", type=int, default=0, help="0 = all cores")
    parser.add_argument("--skip-dense", action="store_true", help="BM25 only")
    args = parser.parse_args()

    settings = get_settings()
    chunks = load_chunks(settings)
    print(f"chunks to index : {len(chunks)}")

    started = time.perf_counter()
    sparse = BM25Store(settings)
    sparse.build(chunks)
    print(f"BM25 built      : {sparse.size} documents in {time.perf_counter() - started:.1f}s")

    if args.skip_dense:
        return 0

    embedder = get_embedder(settings)
    print(f"embedder        : {embedder.name} ({embedder.dimensions} dims)")

    store = QdrantStore(settings, embedder.dimensions)
    print(f"qdrant mode     : {store.mode}")
    try:
        store.recreate()
    except QdrantUnavailableError as exc:
        print(f"\n{exc}\n")
        return 2

    started = time.perf_counter()
    for start in range(0, len(chunks), args.batch):
        batch = chunks[start : start + args.batch]
        vectors = embedder.embed_documents([c.text for c in batch], parallel=args.parallel or None)
        store.upsert(batch, vectors)
        done = min(start + args.batch, len(chunks))
        print(f"  embedded {done}/{len(chunks)}", flush=True)

    elapsed = time.perf_counter() - started
    print(f"\ndense indexed   : {store.count()} vectors in {elapsed:.1f}s")
    print(f"                  ({len(chunks) / max(elapsed, 1e-6):.0f} chunks/sec)")
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
