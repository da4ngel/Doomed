"""FROZEN CONTRACTS. Propose changes as an ADR before touching this file.

WHY these are frozen on day zero: ``claims[]`` with per-claim ``citation_ids`` cannot
be retrofitted. Groundedness is *computed* from it as

    count(claims where support != "inferred") / count(claims)

so it is a number rather than an opinion. Every downstream component - the composer,
the verifier, the eval harness, the Postman assertions - reads that shape. Changing it
on D2 means rewriting all four.

The seam between the knowledge layer and the reasoning layer is POST /v1/search, whose
request and response models live at the bottom of this file. That seam is what lets a
second builder work against fixtures without ever being blocked on ingestion.

Source of truth: docs/master-plan.md sections 2.2 and 2.4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

#: 1 official reference, 2 encyclopaedic, 3 primary narrative, 4 primary record,
#: 5 unreliable/folkloric. Tier 4 is primary evidence but partial; tier 5 is
#: attested but unreliable. A4 resolves conflicts by tier, corroboration as tiebreak.
AuthorityTier = Annotated[int, Field(ge=1, le=5)]

BlockType = Literal["text", "table", "figure", "caption", "heading"]

#: "inferred" is the only value that does NOT count toward groundedness.
SupportLabel = Literal["corroborated", "single_source", "disputed", "inferred"]

QueryIntent = Literal["direct", "visual", "comparison", "multi_hop", "contradiction", "exploratory"]

AnswerMode = Literal["auto", "rich", "graph", "agent"]

SearchMode = Literal["dense", "sparse", "hybrid"]

#: Read off the real dev questions and the wiki infobox fields (corpus findings 3).
RelationPredicate = Literal[
    "member_of",
    "commands",
    "wields",
    "bore_since",
    "mentor_of",
    "born_in",
    "ruled_by",
    "located_in",
    "lair_of",
    "won",
    "fought_in",
    "allied_with",
    "secret",
    "housed_at",
    "has_member",
]

EntityType = Literal["Character", "Faction", "Artifact", "Event", "Location", "Component", "Title"]

WarningType = Literal[
    "low_ocr_confidence",
    "instruction_like_text_in_source",
    "normalization_skipped",
    "asset_unresolved",
    "claim_downgraded",
    "budget_exhausted",
    "tool_failure",
]

#: [x0, y0, x1, y1] in PDF points, origin top-left.
BBox = Annotated[list[float], Field(min_length=4, max_length=4)]


class Frozen(BaseModel):
    """Base for the frozen contracts. Extra fields are rejected, not silently dropped."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Ingestion-side models (master-plan 2.2)
# --------------------------------------------------------------------------


class Document(Frozen):
    doc_id: str
    path: str
    title: str
    source_type: str
    authority_tier: AuthorityTier
    tier_reason: str = ""
    format: Literal["pdf", "docx", "md", "txt", "png", "json", "other"]
    page_count: int = 0
    checksum: str = ""
    version: int = 1
    ingest_status: Literal["pending", "ok", "partial", "failed"] = "pending"
    ingest_error: str | None = None
    ingested_at: datetime | None = None


class Block(Frozen):
    """The atomic unit of extraction.

    For figures, ``text`` holds the VLM description plus any OCR text. That
    concatenation is what makes an image searchable at all - roughly 55 of the 85
    corpus images yield zero OCR characters, so description is the only signal.
    """

    block_id: str
    doc_id: str
    page: int
    order: int
    block_type: BlockType
    text: str = ""
    asset_path: str | None = None
    bbox: BBox | None = None
    section_path: list[str] = Field(default_factory=list)
    caption_ref: str | None = None
    ocr_confidence: float | None = None
    token_count: int = 0
    checksum: str = ""


class Chunk(Frozen):
    chunk_id: str
    doc_id: str
    block_ids: list[str] = Field(default_factory=list)
    text: str
    page_span: tuple[int, int] | None = None
    section_path: list[str] = Field(default_factory=list)
    authority_tier: AuthorityTier
    source_type: str
    embedding_id: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    token_count: int = 0


class Entity(Frozen):
    entity_id: str
    canonical_name: str
    type: EntityType
    aliases: list[str] = Field(default_factory=list)
    mention_count: int = 0
    doc_ids: list[str] = Field(default_factory=list)


class Relation(Frozen):
    """No unsourced edges, ever. ``evidence_chunk_id`` is required, not optional."""

    subject_id: str
    predicate: RelationPredicate
    object_id: str
    evidence_chunk_id: str
    authority_tier: AuthorityTier
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    qualifier: str | None = None  # e.g. "since 336 AS"


# --------------------------------------------------------------------------
# Answer packet (master-plan 2.4)
# --------------------------------------------------------------------------


class Claim(Frozen):
    """One material assertion, bound to the citations that support it.

    THE piece that cannot be retrofitted. Groundedness is computed from ``support``.
    """

    claim_id: str
    text: str
    citation_ids: list[str] = Field(default_factory=list)
    support: SupportLabel
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Citation(Frozen):
    id: str
    chunk_id: str
    doc_id: str
    title: str
    page: int | None = None
    bbox: BBox | None = None
    section_path: list[str] = Field(default_factory=list)
    source_type: str
    authority_tier: AuthorityTier
    excerpt: str
    excerpt_sha256: str
    score: float = 0.0
    relation: Literal["supports", "contradicts", "context"] = "supports"


class Visual(Frozen):
    """Resolved by a ``[FIG:id]`` marker in ``answer_markdown``.

    ``why`` is rendered under the figure in the UI, so a visual that cannot justify
    its own presence is dropped rather than shown.
    """

    id: str
    type: Literal["figure", "table", "page_crop"]
    url: str
    caption: str = ""
    doc_id: str
    page: int | None = None
    bbox: BBox | None = None
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    why: str = ""


class GraphNode(Frozen):
    id: str
    type: Literal["entity", "claim", "document", "visual", "sub_question"]
    label: str


class GraphEdge(Frozen):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    type: Literal["supports", "contradicts", "retrieved_from", "merged_into", "relates"]


class EvidenceGraph(Frozen):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    paths: list[list[str]] = Field(default_factory=list)


class Conflict(Frozen):
    """A disagreement between sources, with the resolution and its reasoning.

    When tiers are equal and sources disagree, ``resolution`` is "unresolved" and both
    sides are surfaced. Refusing to resolve is the feature, not a gap.
    """

    attribute: str
    claim_a: str
    sources_a: list[str] = Field(default_factory=list)
    tier_a: AuthorityTier
    claim_b: str
    sources_b: list[str] = Field(default_factory=list)
    tier_b: AuthorityTier
    resolution: Literal["tier_1_corroborated", "higher_tier", "corroboration_count", "unresolved"]
    rationale: str


class Warning(Frozen):
    type: WarningType
    doc_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    value: float | None = None
    action: str | None = None
    detail: str | None = None


class TraceStep(Frozen):
    """Rendered live in the trace panel.

    ``learned`` and ``missing`` are what make the 1C loop demonstrable rather than
    claimed - they are the strings a judge reads on video.
    """

    step: int
    agent: str
    action: str
    query: str | None = None
    found: int = 0
    new_gold_docs: int = 0
    learned: str = ""
    missing: str = ""
    latency_ms: int = 0


class UsageRecord(Frozen):
    step: int
    model: str
    routing_reason: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    cache: Literal["hit", "miss"] = "miss"
    fallback_used: bool = False


class AnswerPacket(Frozen):
    """The whole system in one object."""

    trace_id: str
    mode: AnswerMode
    answer_markdown: str = ""
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    visuals: list[Visual] = Field(default_factory=list)
    evidence_graph: EvidenceGraph = Field(default_factory=EvidenceGraph)
    conflicts: list[Conflict] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    iterations: int = 0
    partial: bool = False
    reasoning_trace: list[TraceStep] = Field(default_factory=list)
    usage: list[UsageRecord] = Field(default_factory=list)

    def groundedness(self) -> float:
        """Computed, not judged. The whole point of freezing ``claims[]`` on D0."""
        if not self.claims:
            return 0.0
        grounded = sum(1 for c in self.claims if c.support != "inferred")
        return grounded / len(self.claims)


# --------------------------------------------------------------------------
# THE SEAM: POST /v1/search. Frozen and never renegotiated.
# --------------------------------------------------------------------------


class SearchFilters(Frozen):
    source_type: list[str] | None = None
    authority_tier: list[AuthorityTier] | None = None
    doc_id: list[str] | None = None
    block_type: list[BlockType] | None = None


class SearchRequest(Frozen):
    query: str
    mode: SearchMode = "hybrid"
    k: int = Field(default=10, ge=1, le=100)
    rerank: bool = True
    expand: bool = False
    filters: SearchFilters = Field(default_factory=SearchFilters)


class SearchHit(Frozen):
    chunk_id: str
    doc_id: str
    title: str
    text: str
    score: float
    page: int | None = None
    section_path: list[str] = Field(default_factory=list)
    source_type: str
    authority_tier: AuthorityTier
    asset_ids: list[str] = Field(default_factory=list)
    bbox: BBox | None = None
    #: Per-retriever contribution, so the ablation table can attribute a win to the
    #: component that actually produced it rather than to the pipeline as a whole.
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rerank_score: float | None = None


class SearchResponse(Frozen):
    hits: list[SearchHit] = Field(default_factory=list)
    total: int = 0
    mode: SearchMode = "hybrid"
    reranked: bool = False
    latency_ms: int = 0


class ChatRequest(Frozen):
    question: str
    mode: AnswerMode = "auto"
    budget: int = Field(default=6, ge=1, le=12)
    conversation_id: str | None = None


class HealthResponse(Frozen):
    status: Literal["ok"] = "ok"
    version: str


class ReadyResponse(Frozen):
    status: Literal["ready", "degraded", "not_ready"]
    documents: int = 0
    chunks: int = 0
    images_described: int = 0
    entities: int = 0
    relations: int = 0
    providers: list[str] = Field(default_factory=list)
    index_backend: str = ""
    #: Models loaded. A cold first request is ~30x a warm one.
    warm: bool = False
    detail: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Graph endpoints.
#
# ADDITIVE ONLY. The frozen contracts above are untouched - these are new request and
# response models for POST /v1/graph/*, which the reasoning layer calls to walk hop
# chains. Adding models beside the frozen ones needs no ADR; changing one does.
# --------------------------------------------------------------------------


class GraphNeighborsRequest(Frozen):
    entity: str
    hops: int = Field(default=1, ge=1, le=3)
    rel_types: list[RelationPredicate] | None = None
    max_nodes: int = Field(default=200, ge=1, le=1000)


class GraphEdgeOut(Frozen):
    """An edge with the evidence that licenses it. No unsourced edges leave the API."""

    subject_id: str
    subject: str
    predicate: RelationPredicate
    object_id: str
    object: str
    evidence_chunk_id: str
    authority_tier: AuthorityTier
    qualifier: str | None = None


class GraphNeighborsResponse(Frozen):
    entity_id: str
    resolved: bool
    entities: list[Entity] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)
    truncated: bool = False


class GraphPathsRequest(Frozen):
    from_entity: str = Field(alias="from")
    to_entity: str = Field(alias="to")
    max_hops: int = Field(default=3, ge=1, le=5)
    max_paths: int = Field(default=10, ge=1, le=50)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GraphPath(Frozen):
    """One route, with every hop's evidence.

    `distinct` collapses routes by entity chain: the same chain attested by an infobox
    row and a prose sentence is one route corroborated twice, not two routes.
    """

    hops: list[GraphEdgeOut] = Field(default_factory=list)
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    readable: str = ""


class GraphPathsResponse(Frozen):
    from_id: str
    to_id: str
    resolved: bool
    paths: list[GraphPath] = Field(default_factory=list)
