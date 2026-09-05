"""Qdrant vector store, one code path for the Docker service and the embedded file.

WHY both modes from one class: the team runs the Docker service (ADR-004 amendment), but
the test suite and CI must not need a running daemon to pass. Setting `QDRANT_URL`
chooses the service; leaving it unset uses the embedded file at `QDRANT_PATH`. Identical
API, so nothing downstream knows or cares which is live.

WHY payload filtering rather than post-filtering: `SearchFilters` narrows by
`authority_tier` and `source_type`, and those are exactly the filters the ablation table
toggles. Filtering after retrieval would silently shrink k - ask for 10 tier-1 chunks,
get 3, and the recall number quietly measures something else.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.api.schemas import Chunk, SearchFilters
from src.core.config import Settings, get_settings

log = logging.getLogger(__name__)

COLLECTION = "ashen_chunks"

#: Namespace for deriving stable point ids from chunk ids.
_POINT_NAMESPACE = uuid.UUID("6f1d2c3a-0b4e-5f6a-8b9c-0d1e2f3a4b5c")


def point_id(chunk_id: str) -> str:
    """Deterministic point id for a chunk. Stable across runs, unique across batches."""
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


class QdrantUnavailableError(RuntimeError):
    """The configured Qdrant service could not be reached. Names the fix."""

    def __init__(self, url: str, cause: Exception) -> None:
        super().__init__(
            f"Qdrant at {url} is unreachable ({type(cause).__name__}). "
            "Start it with `docker compose up -d qdrant`, or unset QDRANT_URL to use the "
            "embedded store at QDRANT_PATH."
        )


class QdrantStore:
    def __init__(self, settings: Settings | None = None, dimensions: int = 384) -> None:
        self.settings = settings or get_settings()
        self.dimensions = dimensions
        self._client: Any = None

    @property
    def mode(self) -> str:
        return "server" if self.settings.qdrant_url else "embedded"

    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            if self.settings.qdrant_url:
                try:
                    client = QdrantClient(url=self.settings.qdrant_url, timeout=30)
                    client.get_collections()  # fail fast, with a message that helps
                except Exception as exc:  # noqa: BLE001 - re-raised with the remedy
                    raise QdrantUnavailableError(self.settings.qdrant_url, exc) from exc
                self._client = client
            else:
                self.settings.qdrant_path.mkdir(parents=True, exist_ok=True)
                self._client = QdrantClient(path=str(self.settings.qdrant_path))
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def recreate(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        client = self.client()
        if client.collection_exists(COLLECTION):
            client.delete_collection(COLLECTION)
        client.create_collection(
            COLLECTION,
            vectors_config=VectorParams(size=self.dimensions, distance=Distance.COSINE),
        )

    def count(self) -> int:
        client = self.client()
        if not client.collection_exists(COLLECTION):
            return 0
        return int(client.count(COLLECTION).count)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Store vectors with the payload the filters need.

        Point ids are a deterministic UUID5 of the chunk_id, NOT an enumeration index.
        Enumerating restarted at 0 for every batch, so each batch of 256 silently
        overwrote the previous one and a 2,441-chunk corpus indexed as 256 vectors -
        the run reported success throughout. A content-derived id also makes re-indexing
        idempotent instead of duplicating every point.
        """
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=point_id(chunk.chunk_id),
                vector=vector,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "authority_tier": chunk.authority_tier,
                    "source_type": chunk.source_type,
                    "section_path": chunk.section_path,
                    "asset_ids": chunk.asset_ids,
                    "page_span": list(chunk.page_span) if chunk.page_span else None,
                    "token_count": chunk.token_count,
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        client = self.client()
        for start in range(0, len(points), 256):
            client.upsert(COLLECTION, points[start : start + 256])

    @staticmethod
    def _to_filter(filters: SearchFilters | None):
        if filters is None:
            return None
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        conditions = []
        if filters.authority_tier:
            conditions.append(
                FieldCondition(key="authority_tier", match=MatchAny(any=filters.authority_tier))
            )
        if filters.source_type:
            conditions.append(
                FieldCondition(key="source_type", match=MatchAny(any=filters.source_type))
            )
        if filters.doc_id:
            conditions.append(FieldCondition(key="doc_id", match=MatchAny(any=filters.doc_id)))
        return Filter(must=conditions) if conditions else None

    def search(
        self, vector: list[float], k: int = 10, filters: SearchFilters | None = None
    ) -> list[tuple[str, float, dict]]:
        """Return (chunk_id, score, payload), best first."""
        client = self.client()
        if not client.collection_exists(COLLECTION):
            return []
        result = client.query_points(
            COLLECTION,
            query=vector,
            limit=k,
            query_filter=self._to_filter(filters),
            with_payload=True,
        )
        return [(p.payload["chunk_id"], float(p.score), p.payload) for p in result.points]
