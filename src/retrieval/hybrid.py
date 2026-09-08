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
from src.retrieval.expand import (
    Expansion,
    build_doc_chunks,
    graph_expand,
    section_expand,
)
from src.retrieval.rrf import reciprocal_rank_fusion

log = logging.getLogger(__name__)

#: Fetch deeper than k before fusing and reranking; the best chunk is often not in the
#: top-k of either retriever alone, which is the entire premise of hybrid search.
CANDIDATE_MULTIPLIER = 4

#: Share of k that expansion may claim, taken from the bottom of the base ranking.
#: Expansion spends the same budget rather than extending it (ADR-009): appending
#: would make row 6 unable to lose, and the gain would be the extra evidence rather
#: than the graph. Half is the ceiling so the base retriever always keeps the top.
EXPANSION_SHARE = 0.5


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
        self._graph = None
        self._vocabulary: list | None = None
        self._doc_chunks: dict[str, list[str]] | None = None

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

        if len(scores) != len(hits):
            # strict=False silently left the tail of `hits` unscored, so those chunks
            # sorted to the bottom on a default of 0.0 and effectively vanished, with
            # nothing logged. A reranker that returns the wrong number of scores is
            # broken; fall back to the fused order rather than quietly dropping evidence.
            log.warning(
                "rerank returned %d scores for %d hits; using fused order",
                len(scores),
                len(hits),
            )
            return hits[:limit]

        for hit, score in zip(hits, scores, strict=True):
            hit.rerank_score = float(score)
        return sorted(hits, key=lambda h: -getattr(h, "rerank_score", 0.0))[:limit]

    # -- expansion -------------------------------------------------------

    def _graph_handles(self):
        """Load the graph and the entity vocabulary once, on first expanded search.

        Deliberately lazy: the overwhelming majority of requests do not expand, and a
        retriever built for a BM25-only ablation row should not pay to open a SQLite
        graph it will never read.
        """
        if self._graph is None:
            from src.graph.store import GraphStore

            self._graph = GraphStore()
            _, self._vocabulary = self._graph.all_entities(limit=5000)
            self._doc_chunks = build_doc_chunks(self.sparse.chunk_ids, self.sparse.metadata)
        return self._graph, self._vocabulary or [], self._doc_chunks or {}

    def _expand(self, request, hits: list, budget: int) -> Expansion:
        """Collect expansion candidates for `request`, up to `budget` chunks.

        Graph first when both are asked for: it is the only one that can reach a
        document the base retrieval missed, so it should get the scarce slots.
        Section expansion fills whatever is left.
        """
        exclude = {h.chunk_id for h in hits}
        merged = Expansion()

        if request.expand_mode in {"graph", "both"}:
            try:
                graph, vocabulary, doc_chunks = self._graph_handles()
                merged = graph_expand(
                    request.query,
                    graph,
                    vocabulary,
                    doc_chunks,
                    max_chunks=budget,
                    # Documents already retrieved cannot add coverage, so a slot
                    # spent on one is a slot wasted.
                    exclude_docs={h.payload.get("doc_id", "") for h in hits},
                )
            except Exception as exc:  # noqa: BLE001 - expansion is an improvement
                log.warning("graph expansion unavailable: %s", exc)

        if request.expand_mode in {"section", "both"} and len(merged.chunk_ids) < budget:
            try:
                extra = section_expand(
                    [h.chunk_id for h in hits],
                    self.sparse.chunk_ids,
                    self.sparse.metadata,
                    exclude=exclude | set(merged.chunk_ids),
                )
            except Exception as exc:  # noqa: BLE001 - same reason
                log.warning("section expansion unavailable: %s", exc)
            else:
                for chunk_id in extra.chunk_ids:
                    if len(merged.chunk_ids) >= budget:
                        break
                    merged.chunk_ids.append(chunk_id)
                    merged.reasons[chunk_id] = extra.reasons[chunk_id]

        merged.chunk_ids = merged.chunk_ids[:budget]
        merged.reasons = {c: merged.reasons[c] for c in merged.chunk_ids}
        return merged

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

        expansion = Expansion()
        if request.expand and fused:
            budget = min(
                int(request.k * EXPANSION_SHARE),
                max(len(fused) - 1, 0),
            )
            if budget > 0:
                expansion = self._expand(request, fused, budget)
                if expansion.chunk_ids:
                    # Evict the weakest base hits rather than growing the response,
                    # so coverage@k stays comparable with the unexpanded row.
                    fused = fused[: request.k - len(expansion.chunk_ids)]

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

        hits += [
            _hit_from_metadata(chunk_id, self.sparse.metadata(chunk_id))
            for chunk_id in expansion.chunk_ids
        ]

        return SearchResponse(
            hits=hits,
            total=len(hits),
            mode=request.mode,
            reranked=reranked,
            latency_ms=int((time.perf_counter() - started) * 1000),
            expanded=len(expansion.chunk_ids),
            expansion_reasons=dict(expansion.reasons),
        )


def _hit_from_metadata(chunk_id: str, payload: dict) -> SearchHit:
    """Build a hit for a chunk no retriever scored.

    `score` is 0.0 and all three rank fields stay None - that combination is the
    unambiguous signal that this chunk arrived by expansion, so a consumer never has
    to guess whether a 0.0 means 'irrelevant' or 'not scored'. The justification lives
    in `SearchResponse.expansion_reasons`, keyed by chunk id.
    """
    return SearchHit(
        chunk_id=chunk_id,
        doc_id=payload.get("doc_id", ""),
        title=_title(payload),
        text=payload.get("text", ""),
        score=0.0,
        page=(payload.get("page_span") or [None])[0],
        section_path=payload.get("section_path") or [],
        source_type=payload.get("source_type", "unknown"),
        authority_tier=payload.get("authority_tier", 4),
        asset_ids=payload.get("asset_ids") or [],
    )


def _title(payload: dict) -> str:
    section = payload.get("section_path") or []
    if section:
        return " > ".join(str(s) for s in section)
    return str(payload.get("doc_id", "")).replace("_", " ")
