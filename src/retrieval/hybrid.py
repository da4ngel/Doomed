"""The retrieval pipeline behind POST /v1/search.

Each stage is independently toggleable — dense, sparse, fusion, rerank — because the
ablation table is nine configurations of this one function, not nine code paths. If
"+rerank" required a different implementation, the row would be measuring two changes at
once and the number would mean nothing.

Every hit reports `dense_rank`, `sparse_rank` and `rerank_score`, so a win can be
attributed to the component that actually produced it rather than to the pipeline as a
whole.
"""

from __future__ import annotations

import logging
import time

from src.api.schemas import SearchHit, SearchRequest, SearchResponse
from src.core.config import Settings, get_settings
from src.indexing.bm25_store import BM25Store
from src.indexing.embed import Embedder, get_embedder
from src.indexing.qdrant_store import QdrantStore
from src.retrieval.rrf import reciprocal_rank_fusion

log = logging.getLogger(__name__)

#: Fetch deeper than k before fusing and reranking; the best chunk is often not in the
#: top-k of either retriever alone, which is the entire premise of hybrid search.
CANDIDATE_MULTIPLIER = 4


class Retriever:
    """Holds the loaded index. Built once and reused - loading is the slow part."""

    def __init__(
        self,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
        vector_store: QdrantStore | None = None,
        sparse_store: BM25Store | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder or get_embedder(self.settings)
        self.vectors = vector_store or QdrantStore(self.settings, self.embedder.dimensions)
        self.sparse = sparse_store or BM25Store(self.settings)
        self._reranker = None

    # -- rerank ----------------------------------------------------------

    def _rerank(self, query: str, hits: list, limit: int) -> list:
        """Cross-encoder rerank. Degrades to the fused order if the model is missing."""
        if not hits:
            return hits
        try:
            if self._reranker is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                self._reranker = TextCrossEncoder(
                    model_name=self.settings.rerank_model_local,
                    cache_dir=str(self.settings.index_dir.parent / "models"),
                )
            documents = [h.payload.get("text", "") for h in hits]
            scores = list(self._reranker.rerank(query, documents))
        except Exception as exc:  # noqa: BLE001 - reranking is an improvement, not a gate
            log.warning("rerank unavailable, using fused order: %s", exc)
            return hits[:limit]

        for hit, score in zip(hits, scores, strict=False):
            hit.rerank_score = float(score)
        return sorted(hits, key=lambda h: -getattr(h, "rerank_score", 0.0))[:limit]

    # -- search ----------------------------------------------------------

    def search(self, request: SearchRequest) -> SearchResponse:
        started = time.perf_counter()
        depth = max(request.k * CANDIDATE_MULTIPLIER, request.k)

        dense: list[tuple[str, float, dict]] = []
        sparse: list[tuple[str, float, dict]] = []

        if request.mode in {"dense", "hybrid"}:
            vector = self.embedder.embed_query(request.query)
            dense = self.vectors.search(vector, k=depth, filters=request.filters)

        if request.mode in {"sparse", "hybrid"}:
            sparse = self.sparse.search(request.query, k=depth, filters=request.filters)

        fused = reciprocal_rank_fusion(dense, sparse, limit=depth)
        for hit in fused:
            hit.rerank_score = None  # type: ignore[attr-defined]

        reranked = False
        if request.rerank and fused:
            fused = self._rerank(request.query, fused, request.k)
            reranked = any(getattr(h, "rerank_score", None) is not None for h in fused)
        else:
            fused = fused[: request.k]

        hits = [
            SearchHit(
                chunk_id=hit.chunk_id,
                doc_id=hit.payload.get("doc_id", ""),
                title=_title(hit.payload),
                text=hit.payload.get("text", ""),
                score=round(hit.score, 6),
                page=(hit.payload.get("page_span") or [None])[0],
                section_path=hit.payload.get("section_path") or [],
                source_type=hit.payload.get("source_type", "unknown"),
                authority_tier=hit.payload.get("authority_tier", 4),
                asset_ids=hit.payload.get("asset_ids") or [],
                dense_rank=hit.dense_rank,
                sparse_rank=hit.sparse_rank,
                rerank_score=getattr(hit, "rerank_score", None),
            )
            for hit in fused
        ]

        return SearchResponse(
            hits=hits,
            total=len(hits),
            mode=request.mode,
            reranked=reranked,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _title(payload: dict) -> str:
    section = payload.get("section_path") or []
    if section:
        return " > ".join(str(s) for s in section)
    return str(payload.get("doc_id", "")).replace("_", " ")
