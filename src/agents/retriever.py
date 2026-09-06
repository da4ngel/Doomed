"""A2 executes one selected action; discovery drives A3, never an implicit chain."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

from pydantic import Field

from src.agents.runtime import KnowledgeClient
from src.api.schemas import (
    Entity,
    Frozen,
    GraphEdgeOut,
    GraphNeighborsResponse,
    GraphPathsResponse,
    SearchFilters,
    SearchHit,
    SearchResponse,
    Warning,
)


class Action(Frozen):
    action: str = "hybrid_search"
    query: str = ""
    k: int = Field(default=10, ge=1, le=100)
    rerank: bool = True
    filters: SearchFilters = Field(default_factory=SearchFilters)
    args: dict[str, Any] = Field(default_factory=dict)


class Evidence(Frozen):
    chunks: list[SearchHit] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    new_gold_docs: int = 0
    new_chunks: int = 0
    latency_ms: int = 0


def scan_instructions(chunks: list[SearchHit]) -> list[Warning]:
    warnings: list[Warning] = []
    for chunk in chunks:
        for match in re.finditer(
            r"\b(?:ignore|you must|disregard|forget previous|system prompt)\b", chunk.text, re.I
        ):
            warnings.append(
                Warning(
                    type="instruction_like_text_in_source",
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    detail=match[0],
                    action="Kept as evidence, never executed as instructions",
                )
            )
    return warnings


class RetrievalAgent:
    def __init__(self, client: KnowledgeClient) -> None:
        self.client = client

    def execute(
        self,
        action: Action,
        *,
        seen_chunks: set[str] | None = None,
        seen_docs: set[str] | None = None,
    ) -> Evidence:
        started = time.monotonic()
        try:
            if action.action in {"hybrid_search", "figure_search", "list_mentions"}:
                result = self._search(action)
            elif action.action in {"graph_neighbors", "graph_paths"}:
                result = self._graph(action)
            else:
                result = Evidence(
                    warnings=[
                        Warning(
                            type="tool_failure",
                            detail=(
                                f"Unsupported action {action.action}; "
                                "read_section is not exposed by P1"
                            ),
                        )
                    ]
                )
        except Exception as error:
            result = Evidence(
                warnings=[
                    Warning(type="tool_failure", detail=f"{action.action}: {type(error).__name__}")
                ]
            )
        result.warnings.extend(scan_instructions(result.chunks))
        result.new_gold_docs = len({c.doc_id for c in result.chunks} - (seen_docs or set()))
        result.new_chunks = len({c.chunk_id for c in result.chunks} - (seen_chunks or set()))
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    def _search(self, action: Action) -> Evidence:
        filters = action.filters.model_dump(exclude_none=True)
        if action.action == "figure_search":
            filters["source_type"] = ["figure_plate", "wiki_image"]
        query = action.args.get("entity_name", action.query)
        body = {
            "query": query,
            "k": action.k,
            "filters": filters,
            "rerank": action.rerank,
            "mode": "hybrid",
        }
        warnings: list[Warning] = []
        for mode, rerank in [("hybrid", action.rerank), ("hybrid", False), ("sparse", False)]:
            body.update(mode=mode, rerank=rerank)
            try:
                parsed = SearchResponse.model_validate(
                    self.client.request("POST", "/v1/search", body)
                )
                return Evidence(chunks=parsed.hits, warnings=warnings)
            except Exception as error:
                warnings.append(
                    Warning(
                        type="tool_failure",
                        detail=(
                            f"{mode}, rerank={rerank}: {type(error).__name__}; "
                            "trying degraded retrieval"
                        ),
                    )
                )
        return Evidence(warnings=warnings)

    def _graph(self, action: Action) -> Evidence:
        result: GraphNeighborsResponse | GraphPathsResponse
        args = action.args
        if action.action == "graph_neighbors":
            body = {
                "entity": args.get("entity_id", action.query),
                "hops": args.get("hops", 1),
                "max_nodes": 100,
            }
            if args.get("rel_types"):
                body["rel_types"] = args["rel_types"]
            result = GraphNeighborsResponse.model_validate(
                self.client.request("POST", "/v1/graph/neighbors", body)
            )
            evidence = Evidence(entities=result.entities, edges=result.edges)
        else:
            body = {
                "from": args.get("from", ""),
                "to": args.get("to", ""),
                "max_hops": args.get("max_hops", 3),
                "max_paths": 10,
            }
            result = GraphPathsResponse.model_validate(
                self.client.request("POST", "/v1/graph/paths", body)
            )
            evidence = Evidence(edges=[edge for path in result.paths for edge in path.hops])
        if not result.resolved:
            evidence.warnings.append(Warning(type="tool_failure", detail="Graph entity unresolved"))
        return evidence

    def assets(self, chunks: list[SearchHit]) -> Evidence:
        """Explicit metadata enrichment, separate from the one-action executor."""
        result = Evidence()
        for asset_id in dict.fromkeys(a for c in chunks for a in c.asset_ids):
            try:
                meta = self.client.request("GET", f"/v1/assets/{quote(asset_id, safe='')}/meta")
                if meta.get("asset_id") != asset_id:
                    raise ValueError("asset metadata ID mismatch")
                result.assets.append(meta)
            except Exception as error:
                result.warnings.append(
                    Warning(type="asset_unresolved", detail=f"{asset_id}: {type(error).__name__}")
                )
        return result
