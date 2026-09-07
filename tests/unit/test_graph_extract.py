"""Tests for LLM relation extraction.

`validate` is the whole safety story of this module, so it gets most of the tests. An
edge that carries a real `evidence_chunk_id` and a relationship the chunk never states is
worse than no edge: it survives every downstream check we have, and it is exactly what an
unconstrained extractor produces.

No LLM is called here. The model's output is the input to these tests.
"""

from __future__ import annotations

from src.api.schemas import Entity
from src.graph.extract import (
    LLM_CONFIDENCE,
    MIN_ENTITIES,
    PREDICATES,
    Candidate,
    ExtractionStats,
    build_prompt,
    validate,
)

PASSAGE = (
    "Sabelle Mournvale bore the Crown of Burned Names through the long winter, "
    "and the Ashen Vanguard answered to her alone."
)


def _entity(entity_id: str, name: str, entity_type: str = "Character") -> Entity:
    return Entity(entity_id=entity_id, canonical_name=name, type=entity_type)


def _candidate(text: str = PASSAGE) -> Candidate:
    return Candidate(
        chunk_id="chronicle:c7",
        doc_id="chronicle",
        text=text,
        authority_tier=3,
        entities=[
            _entity("ent_sabelle_mournvale", "Sabelle Mournvale"),
            _entity("ent_crown_of_burned_names", "The Crown of Burned Names", "Artifact"),
            _entity("ent_ashen_vanguard", "The Ashen Vanguard", "Faction"),
        ],
    )


def _relation(**overrides) -> dict:
    base = {
        "subject_id": "ent_sabelle_mournvale",
        "predicate": "wields",
        "object_id": "ent_crown_of_burned_names",
        "quote": "Sabelle Mournvale bore the Crown of Burned Names through the long winter",
    }
    return {**base, **overrides}


def test_a_well_formed_relation_is_kept() -> None:
    stats = ExtractionStats()
    kept = validate([_relation()], _candidate(), stats)
    assert len(kept) == 1
    assert kept[0].subject_id == "ent_sabelle_mournvale"
    assert kept[0].evidence_chunk_id == "chronicle:c7"


def test_extracted_edges_are_marked_lower_confidence_than_wiki_edges() -> None:
    """A consumer choosing between two contradictory edges must be able to tell which one
    was read off an infobox row and which was read out of prose by a model."""
    kept = validate([_relation()], _candidate(), ExtractionStats())
    assert kept[0].confidence == LLM_CONFIDENCE
    assert kept[0].confidence < 1.0


def test_the_edge_inherits_the_passage_authority_tier() -> None:
    """A relationship stated in a tier-5 ballad must not arrive looking like a codex fact."""
    kept = validate([_relation()], _candidate(), ExtractionStats())
    assert kept[0].authority_tier == 3


def test_an_entity_not_present_in_the_passage_is_dropped() -> None:
    """The model is shown the entities present and asked how they relate. Anything else
    is an invention, however plausible."""
    stats = ExtractionStats()
    kept = validate([_relation(object_id="ent_someone_else")], _candidate(), stats)
    assert kept == []
    assert stats.dropped_unknown_entity == 1


def test_a_predicate_outside_the_frozen_vocabulary_is_dropped() -> None:
    stats = ExtractionStats()
    kept = validate([_relation(predicate="betrayed")], _candidate(), stats)
    assert kept == []
    assert stats.dropped_bad_predicate == 1


def test_a_self_loop_is_dropped() -> None:
    stats = ExtractionStats()
    kept = validate([_relation(object_id="ent_sabelle_mournvale")], _candidate(), stats)
    assert kept == []
    assert stats.dropped_self_loop == 1


def test_an_unquoted_relation_is_dropped() -> None:
    stats = ExtractionStats()
    kept = validate([_relation(quote="")], _candidate(), stats)
    assert kept == []
    assert stats.dropped_no_quote == 1


def test_a_quote_the_passage_does_not_contain_is_dropped() -> None:
    """The most important check here. A quote the passage does not contain means the
    model wrote the sentence it wished were there - and that edge would otherwise carry a
    real chunk id into an answer."""
    stats = ExtractionStats()
    kept = validate(
        [_relation(quote="Sabelle Mournvale renounced the Crown of Burned Names")],
        _candidate(),
        stats,
    )
    assert kept == []
    assert stats.dropped_quote_not_in_text == 1


def test_quote_matching_tolerates_whitespace_differences() -> None:
    """Line wrapping in the source must not fail an otherwise verbatim quote."""
    stats = ExtractionStats()
    kept = validate(
        [_relation(quote="Sabelle   Mournvale bore\n the Crown of Burned Names")],
        _candidate(),
        stats,
    )
    assert len(kept) == 1


def test_malformed_items_do_not_crash_the_run() -> None:
    stats = ExtractionStats()
    kept = validate(["not a dict", None, 42], _candidate(), stats)  # type: ignore[list-item]
    assert kept == []
    assert stats.proposed == 3


def test_every_kept_edge_counts_and_every_drop_counts() -> None:
    """The stats are the evidence that the guards fire, so they must be exhaustive."""
    stats = ExtractionStats()
    proposed = [
        _relation(),
        _relation(predicate="betrayed"),
        _relation(object_id="ent_nobody"),
    ]
    validate(proposed, _candidate(), stats)
    dropped = (
        stats.dropped_unknown_entity
        + stats.dropped_bad_predicate
        + stats.dropped_self_loop
        + stats.dropped_no_quote
        + stats.dropped_quote_not_in_text
    )
    assert stats.proposed == 3
    assert stats.kept + dropped == stats.proposed


# -- prompt construction --------------------------------------------------


def test_the_passage_enters_the_prompt_inside_an_evidence_block() -> None:
    """CLAUDE.md non-negotiable: retrieved text never sits in the instruction position."""
    message, _ = build_prompt(_candidate())
    assert "BEGIN_EVIDENCE" in message
    assert "END_EVIDENCE" in message
    instruction_half, evidence_half = message.split("BEGIN_EVIDENCE", 1)
    assert PASSAGE not in instruction_half
    assert PASSAGE in evidence_half


def test_the_prompt_names_the_closed_entity_and_predicate_vocabularies() -> None:
    message, _ = build_prompt(_candidate())
    assert "ent_sabelle_mournvale" in message
    for predicate in ("mentor_of", "wields", "won"):
        assert predicate in message


def test_an_in_world_order_in_the_passage_is_reported() -> None:
    message, suspicious = build_prompt(
        _candidate("By order of the Warden, Sabelle Mournvale was struck from the rolls.")
    )
    assert suspicious
    assert "BEGIN_EVIDENCE" in message


def test_the_predicate_vocabulary_matches_the_frozen_schema() -> None:
    """If the schema gains a predicate, extraction must be allowed to use it - and if it
    loses one, extraction must stop emitting it."""
    assert "mentor_of" in PREDICATES
    assert "betrayed" not in PREDICATES
    assert MIN_ENTITIES == 2
