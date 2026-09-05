"""POST /v1/search — THE SEAM.

This endpoint and the `SearchRequest`/`SearchResponse` models in `schemas.py` are the
contract between the knowledge layer and the reasoning layer. P2 codes against it with
fixtures and is never blocked on ingestion; P1 can rewrite everything behind it without
breaking a single caller. It is frozen: changes need an ADR.

The retriever is loaded once at first use rather than per request - loading the ONNX
model and the BM25 arrays takes seconds, answering takes milliseconds.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import APIRouter, HTTPException

from src.api.schemas import SearchRequest, SearchResponse
from src.indexing.qdrant_store import QdrantUnavailableError
from src.retrieval.hybrid import Retriever

log = logging.getLogger(__name__)

router = APIRouter(tags=["02 Retrieval"])


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    return Retriever()


@router.post("/v1/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Retrieval primitive: dense, sparse or hybrid, with optional rerank and filters."""
    if not request.query.strip():
        # An empty query is a client bug, not a zero-result search. Saying so is more
        # useful than returning an empty list that looks like "nothing matched".
        raise HTTPException(status_code=422, detail="query must not be empty")

    try:
        return get_retriever().search(request)
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{exc} - the index has not been built yet",
        ) from exc
