"""BM25 sparse index over the same chunks.

WHY sparse matters here more than in a typical corpus: the archive is entirely invented
proper nouns, and the corpus is built with near-miss decoys. `greyfell_citadel` (garrison
3,695, image only) sits beside `ironfell_citadel` (1,096, in text); `The Thrice-Bound
Edge` (94) beside `The Thrice-Bound Lantern` (55). Dense similarity actively pulls those
together - they are semantically near-identical. Exact lexical matching is what separates
them, so BM25 is not a baseline to beat, it is half the answer.

That gives the ablation table a concrete story rather than a generic one: row 1 (BM25) vs
row 2 (dense) vs row 4 (hybrid) can be explained with the Edge/Lantern pair.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.api.schemas import Chunk, SearchFilters
from src.core.config import Settings, get_settings

_TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, keeping hyphens and apostrophes.

    `thrice-bound` must survive as a unit - splitting it discards the very distinction
    that separates the Edge from the Lantern.
    """
    return _TOKEN.findall(text.lower())


class BM25Store:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.dir = self.settings.index_dir / "bm25"
        self._retriever = None
        self._chunk_ids: list[str] = []
        self._meta: dict[str, dict] = {}

    def build(self, chunks: list[Chunk]) -> None:
        import bm25s

        corpus = [tokenize(c.text) for c in chunks]
        retriever = bm25s.BM25()
        retriever.index(corpus)

        meta = {
            c.chunk_id: {
                "doc_id": c.doc_id,
                "authority_tier": c.authority_tier,
                "source_type": c.source_type,
                "section_path": c.section_path,
                "asset_ids": c.asset_ids,
                "page_span": list(c.page_span) if c.page_span else None,
                "text": c.text,
            }
            for c in chunks
        }

        self.dir.mkdir(parents=True, exist_ok=True)
        retriever.save(str(self.dir))
        (self.dir / "chunk_ids.json").write_text(
            json.dumps([c.chunk_id for c in chunks]), encoding="utf-8"
        )
        (self.dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        # Populate the in-memory state too. `_load()` short-circuits on `_retriever`
        # being set, so leaving `_meta` empty here made every filter match nothing when
        # a process built and then searched - silently, since an empty result set looks
        # like "no matches" rather than a bug.
        self._retriever = retriever
        self._chunk_ids = [c.chunk_id for c in chunks]
        self._meta = meta

    def _load(self):
        if self._retriever is None:
            import bm25s

            if not (self.dir / "chunk_ids.json").exists():
                raise FileNotFoundError("BM25 index missing - run `python -m src.indexing.build`")
            self._retriever = bm25s.BM25.load(str(self.dir), load_corpus=False)
            self._chunk_ids = json.loads((self.dir / "chunk_ids.json").read_text("utf-8"))
            self._meta = json.loads((self.dir / "meta.json").read_text("utf-8"))
        return self._retriever

    @property
    def size(self) -> int:
        path = self.dir / "chunk_ids.json"
        return len(json.loads(path.read_text("utf-8"))) if path.exists() else 0

    @staticmethod
    def _is_active(filters: SearchFilters | None) -> bool:
        """True only when a filter would actually exclude something.

        WHY this is not `if filters`: SearchRequest.filters is built with
        `default_factory=SearchFilters`, so it is NEVER None, and a plain pydantic model
        has no __bool__ - an empty SearchFilters is truthy. The over-fetch below read as
        "5x depth when filtering", but took that branch on every search ever made,
        filtered or not, on top of the 4x the caller already asks for.
        """
        if filters is None:
            return False
        return bool(filters.authority_tier or filters.source_type or filters.doc_id)

    def _passes(self, chunk_id: str, filters: SearchFilters | None) -> bool:
        if filters is None or not self._is_active(filters):
            return True
        meta = self._meta.get(chunk_id, {})
        if filters.authority_tier and meta.get("authority_tier") not in filters.authority_tier:
            return False
        if filters.source_type and meta.get("source_type") not in filters.source_type:
            return False
        return not (filters.doc_id and meta.get("doc_id") not in filters.doc_id)

    def search(
        self, query: str, k: int = 10, filters: SearchFilters | None = None
    ) -> list[tuple[str, float, dict]]:
        retriever = self._load()
        tokens = tokenize(query)
        if not tokens:
            return []
        # Over-fetch so filtering cannot silently shrink k below what was asked for -
        # but only when a filter is actually set. See _is_active.
        depth = min(k * 5 if self._is_active(filters) else k, len(self._chunk_ids))
        indices, scores = retriever.retrieve([tokens], k=depth)

        results: list[tuple[str, float, dict]] = []
        for position, score in zip(indices[0], scores[0], strict=False):
            chunk_id = self._chunk_ids[int(position)]
            if not self._passes(chunk_id, filters):
                continue
            results.append((chunk_id, float(score), self._meta.get(chunk_id, {})))
            if len(results) >= k:
                break
        return results

    def metadata(self, chunk_id: str) -> dict:
        self._load()
        return self._meta.get(chunk_id, {})

    @property
    def chunk_ids(self) -> list[str]:
        """Every chunk id in index order, which is document order.

        Section expansion needs to know which chunk sits either side of a hit, and
        this list is the only ordering the index actually guarantees - reconstructing
        it by parsing `doc:cN` ids would encode a naming convention as a data
        structure and break the moment an id scheme changes.
        """
        self._load()
        return self._chunk_ids


def load_chunks(settings: Settings | None = None) -> list[Chunk]:
    settings = settings or get_settings()
    path: Path = settings.index_dir / "chunks.jsonl"
    if not path.exists():
        raise FileNotFoundError("run `python -m src.ingestion.chunker` first")
    return [
        Chunk(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
