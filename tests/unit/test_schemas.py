"""Contract tests for the frozen schemas.

These are not "does pydantic work" tests. Each one pins a property that something
downstream depends on, so that an accidental edit to schemas.py fails here rather
than silently changing what groundedness means three days from now.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.schemas import (
    AnswerPacket,
    Block,
    Claim,
    Conflict,
    EvidenceGraph,
    GraphEdge,
    Relation,
    SearchRequest,
)


def _claim(claim_id: str, support: str) -> Claim:
    return Claim(claim_id=claim_id, text="t", citation_ids=["c1"], support=support)


def test_groundedness_counts_everything_except_inferred() -> None:
    packet = AnswerPacket(
        trace_id="tr_1",
        mode="agent",
        claims=[
            _claim("cl_1", "corroborated"),
            _claim("cl_2", "single_source"),
            _claim("cl_3", "disputed"),
            _claim("cl_4", "inferred"),
        ],
    )
    assert packet.groundedness() == 0.75


def test_groundedness_of_a_refusal_is_zero_not_a_crash() -> None:
    """An unanswerable question returns no claims. That must not divide by zero."""
    packet = AnswerPacket(
        trace_id="tr_1",
        mode="agent",
        missing_information=["The archive does not name the fourth signatory house."],
    )
    assert packet.groundedness() == 0.0
    assert packet.claims == []


def test_extra_fields_are_rejected_not_silently_dropped() -> None:
    """A typo in a field name must fail loudly, or half the packet goes missing."""
    with pytest.raises(ValidationError):
        Claim(claim_id="cl_1", text="t", suport="corroborated")  # type: ignore[call-arg]


def test_support_label_vocabulary_is_closed() -> None:
    with pytest.raises(ValidationError):
        _claim("cl_1", "probably_true")


def test_authority_tier_is_bounded_to_1_through_5() -> None:
    for bad in (0, 6, -1):
        with pytest.raises(ValidationError):
            Relation(
                subject_id="e1",
                predicate="member_of",
                object_id="e2",
                evidence_chunk_id="ch1",
                authority_tier=bad,
            )


def test_relation_requires_evidence_chunk_id() -> None:
    """No unsourced edges, ever - a graph edge nobody can cite is not evidence."""
    with pytest.raises(ValidationError):
        Relation(  # type: ignore[call-arg]
            subject_id="e1", predicate="member_of", object_id="e2", authority_tier=2
        )


def test_graph_edge_serialises_as_from_and_to() -> None:
    """`from` is a Python keyword; the wire format must still say "from"."""
    edge = GraphEdge(**{"from": "n1", "to": "n2", "type": "supports"})
    dumped = EvidenceGraph(edges=[edge]).model_dump(by_alias=True)
    assert dumped["edges"][0]["from"] == "n1"
    assert dumped["edges"][0]["to"] == "n2"


def test_conflict_can_stay_unresolved() -> None:
    """Equal tiers that disagree must be surfaceable without picking a winner."""
    conflict = Conflict(
        attribute="Gloamreach founding year",
        claim_a="311 AS",
        sources_a=["wiki_gloamreach"],
        tier_a=2,
        claim_b="318 AS",
        sources_b=["ledger_012"],
        tier_b=2,
        resolution="unresolved",
        rationale="Equal authority tiers and no corroboration on either side.",
    )
    assert conflict.resolution == "unresolved"


def test_bbox_must_have_exactly_four_numbers() -> None:
    with pytest.raises(ValidationError):
        Block(
            block_id="b1",
            doc_id="d1",
            page=1,
            order=0,
            block_type="figure",
            bbox=[1.0, 2.0, 3.0],
        )


def test_search_request_defaults_match_the_frozen_seam() -> None:
    """P2 codes against these defaults; changing them silently breaks the seam."""
    req = SearchRequest(query="Greyfell garrison")
    assert (req.mode, req.k, req.rerank, req.expand) == ("hybrid", 10, True, False)


def test_answer_packet_json_schema_is_generatable() -> None:
    """FastAPI serves this as OpenAPI 3.1 and Postman imports it from the link."""
    schema = AnswerPacket.model_json_schema()
    assert "claims" in schema["properties"]
    assert "citations" in schema["properties"]
