"""POST /v1/graph/neighbors and /v1/graph/paths — sub-track 1B's evidence source.

WHY these are POST and not GET: entity names contain spaces, apostrophes and hyphens
("Cerys Sablewood the Ashen"), and a body avoids a layer of URL encoding that would
otherwise appear in every Postman example and every curl in the README.

Entity resolution is EXACT, deliberately. `greyfell_citadel` and `ironfell_citadel` are
different places with different garrison figures; a fuzzy match between them returns a
wrong number carrying a real citation. When a name does not resolve the response says
`resolved: false` with an empty result rather than guessing - a caller can then ask the
user, which is honest, instead of answering confidently about the wrong place.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter

from src.api.schemas import (
    GraphEdgeOut,
    GraphNeighborsRequest,
    GraphNeighborsResponse,
    GraphPath,
    GraphPathsRequest,
    GraphPathsResponse,
)
from src.core.config import get_settings
from src.graph.store import GraphStore, Hop
from src.graph.wiki_extract import entity_id

router = APIRouter(tags=["03 Graph"])


@lru_cache(maxsize=1)
def get_store() -> GraphStore:
    return GraphStore(get_settings().index_dir / "graph.sqlite")


def _resolve(store: GraphStore, name: str) -> str | None:
    """Name -> entity id. Tries the slug, then an exact canonical-name lookup."""
    candidate = name if name.startswith("ent_") else entity_id(name)
    if store.entity(candidate):
        return candidate
    matches = store.find_entities(name)
    return matches[0].entity_id if matches else None


def _edge_out(hop: Hop, names: dict[str, str]) -> GraphEdgeOut:
    return GraphEdgeOut(
        subject_id=hop.subject_id,
        subject=names.get(hop.subject_id, hop.subject_id),
        predicate=hop.predicate,  # type: ignore[arg-type]
        object_id=hop.object_id,
        object=names.get(hop.object_id, hop.object_id),
        evidence_chunk_id=hop.evidence_chunk_id,
        authority_tier=hop.authority_tier,
        qualifier=hop.qualifier,
    )


@router.post("/v1/graph/neighbors", response_model=GraphNeighborsResponse)
def neighbors(request: GraphNeighborsRequest) -> GraphNeighborsResponse:
    """k-hop expansion around an entity, every edge carrying its evidence."""
    store = get_store()
    resolved = _resolve(store, request.entity)
    if resolved is None:
        return GraphNeighborsResponse(entity_id=request.entity, resolved=False)

    reached, edges = store.neighbors(
        resolved,
        hops=request.hops,
        predicates=list(request.rel_types) if request.rel_types else None,
        max_nodes=request.max_nodes,
    )
    names = store.names()
    entities = [e for e in (store.entity(i) for i in sorted(reached)) if e is not None]

    seen: set[tuple] = set()
    unique_edges = []
    for hop in edges:
        key = (hop.subject_id, hop.predicate, hop.object_id, hop.evidence_chunk_id)
        if key in seen:
            continue
        seen.add(key)
        unique_edges.append(_edge_out(hop, names))

    return GraphNeighborsResponse(
        entity_id=resolved,
        resolved=True,
        entities=entities,
        edges=unique_edges,
        truncated=len(reached) >= request.max_nodes,
    )


@router.post("/v1/graph/paths", response_model=GraphPathsResponse)
def paths(request: GraphPathsRequest) -> GraphPathsResponse:
    """All routes between two entities, up to `max_hops`, with per-hop evidence.

    `readable` is the rendered chain the answer composer quotes, so a 1B answer can show
    its working rather than assert a conclusion.
    """
    store = get_store()
    start = _resolve(store, request.from_entity)
    end = _resolve(store, request.to_entity)
    if start is None or end is None:
        return GraphPathsResponse(
            from_id=request.from_entity, to_id=request.to_entity, resolved=False
        )

    names = store.names()
    found = store.distinct_paths(start, end, request.max_hops, request.max_paths)
    return GraphPathsResponse(
        from_id=start,
        to_id=end,
        resolved=True,
        paths=[
            GraphPath(
                hops=[_edge_out(h, names) for h in chain],
                evidence_chunk_ids=evidence,
                readable=" | ".join(h.as_text(names) for h in chain),
            )
            for chain, evidence in found
        ],
    )
