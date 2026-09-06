"""Tests for context expansion.

The expansion rows of the ablation are only trustworthy if expansion cannot cheat, so
most of these pin a boundary where it would be easy to accidentally inflate a number:
matching an entity that is not in the query, adding a document already retrieved, or
crossing a section boundary the chunker deliberately respected.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.api.schemas import Entity
from src.graph.store import Hop
from src.retrieval.expand import (
    build_doc_chunks,
    doc_slug,
    entities_in_query,
    graph_expand,
    section_expand,
)


def _entity(name: str, entity_type: str = "Faction", docs: list[str] | None = None) -> Entity:
    slug = name.lower().replace(" ", "_").replace("-", "_")
    return Entity(
        entity_id=f"ent_{slug}",
        canonical_name=name,
        type=entity_type,
        doc_ids=docs or [],
    )


@dataclass
class FakeStore:
    """Minimal GraphStore stand-in. Keeps these tests independent of a built index."""

    edges: dict[str, list[Hop]]
    entities: dict[str, Entity]

    def neighbors(self, entity_id: str, hops: int = 1):
        found = self.edges.get(entity_id, [])
        return set(), list(found)

    def entity(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def names(self) -> dict[str, str]:
        return {e.entity_id: e.canonical_name for e in self.entities.values()}


# -- entity matching ------------------------------------------------------


def test_matches_an_entity_named_in_the_query() -> None:
    vocab = [_entity("The Iron-Ring Cartel")]
    found = entities_in_query("who leads the Iron-Ring Cartel", vocab)
    assert [e.canonical_name for e in found] == ["The Iron-Ring Cartel"]


def test_punctuation_and_case_do_not_break_matching() -> None:
    """The corpus uses typographic quotes and en-dashes, so this is realistic input."""
    vocab = [_entity("Thrice-Bound Edge", "Artifact")]
    assert entities_in_query("cost of the THRICE BOUND EDGE?", vocab)


def test_a_near_miss_name_does_not_match() -> None:
    """Finding 13: Greyfell and Ironfell are different places with different garrisons.
    An expansion that resolves one to the other returns a wrong number with a real
    citation, which is the worst failure this system has available to it."""
    vocab = [_entity("Greyfell Citadel", "Location")]
    assert entities_in_query("garrison of Ironfell Citadel", vocab) == []
    assert entities_in_query("garrison of Greyfel Citadell", vocab) == []


def test_the_longer_name_wins_and_the_shorter_is_not_also_reported() -> None:
    vocab = [_entity("The War of Drowned Light", "Event"), _entity("Drowned Light", "Event")]
    found = entities_in_query("who won the War of Drowned Light", vocab)
    assert [e.canonical_name for e in found] == ["The War of Drowned Light"]


def test_title_entities_never_seed_a_walk() -> None:
    """`Title` is the extractor's catch-all and holds infobox values, not names. Seeding
    from one would attach a walk to a phrase rather than to a subject."""
    vocab = [_entity("Fought in The Purge of Blackport", "Title")]
    assert entities_in_query("fought in the purge of blackport", vocab) == []


def test_very_short_names_are_ignored() -> None:
    vocab = [_entity("Ash", "Component")]
    assert entities_in_query("what happened to the ash and the cinders", vocab) == []


# -- graph expansion ------------------------------------------------------


def _one_hop_store() -> FakeStore:
    war = _entity("The Purge of Blackport", "Event", ["wiki/the_purge_of_blackport.md"])
    cartel = _entity("The Iron-Ring Cartel", "Faction", ["wiki/the_iron_ring_cartel.md"])
    hop = Hop(cartel.entity_id, "won", war.entity_id, "wiki/x.md#infobox:Victor", 2)
    return FakeStore(
        edges={war.entity_id: [hop]},
        entities={war.entity_id: war, cartel.entity_id: cartel},
    )


def test_graph_expansion_reaches_the_second_hop_document() -> None:
    """The whole point: the question names the event, the answer needs the victor's
    article, and that article does not contain the event name in a form either retriever
    scores highly."""
    store = _one_hop_store()
    vocab = list(store.entities.values())
    doc_chunks = {"the_iron_ring_cartel": ["the_iron_ring_cartel:c0"]}

    expansion = graph_expand("who won the Purge of Blackport", store, vocab, doc_chunks)

    assert expansion.chunk_ids == ["the_iron_ring_cartel:c0"]
    assert "won" in expansion.reasons["the_iron_ring_cartel:c0"]


def test_an_expanded_chunk_always_carries_a_reason() -> None:
    store = _one_hop_store()
    expansion = graph_expand(
        "who won the Purge of Blackport",
        store,
        list(store.entities.values()),
        {"the_iron_ring_cartel": ["the_iron_ring_cartel:c0"]},
    )
    assert set(expansion.reasons) == set(expansion.chunk_ids)
    assert "wiki/x.md#infobox:Victor" in expansion.reasons["the_iron_ring_cartel:c0"]


def test_a_document_already_retrieved_is_not_added_again() -> None:
    """A slot spent on a document the base retrieval already found buys no coverage."""
    store = _one_hop_store()
    expansion = graph_expand(
        "who won the Purge of Blackport",
        store,
        list(store.entities.values()),
        {"the_iron_ring_cartel": ["the_iron_ring_cartel:c0"]},
        exclude_docs={"the_iron_ring_cartel"},
    )
    assert expansion.chunk_ids == []


def test_no_entity_in_the_query_means_no_expansion() -> None:
    store = _one_hop_store()
    expansion = graph_expand("zzqx wrmbl fthgn", store, list(store.entities.values()), {})
    assert not expansion
    assert expansion.chunk_ids == []


def test_self_loops_are_skipped() -> None:
    """The wiki extractor produces these where an article's infobox names its own
    subject. An edge from a thing to itself licenses no new document."""
    war = _entity("The Purge of Blackport", "Event", ["wiki/the_purge_of_blackport.md"])
    loop = Hop(war.entity_id, "fought_in", war.entity_id, "wiki/x.md#infobox:Conflict", 2)
    store = FakeStore(edges={war.entity_id: [loop]}, entities={war.entity_id: war})

    expansion = graph_expand(
        "the Purge of Blackport",
        store,
        [war],
        {"the_purge_of_blackport": ["the_purge_of_blackport:c0"]},
    )
    assert expansion.chunk_ids == []


def test_the_budget_is_respected() -> None:
    war = _entity("The Purge of Blackport", "Event")
    neighbours = [_entity(f"Faction {i}", "Faction", [f"wiki/faction_{i}.md"]) for i in range(5)]
    hops = [
        Hop(n.entity_id, "fought_in", war.entity_id, f"wiki/{i}.md#row", 2)
        for i, n in enumerate(neighbours)
    ]
    store = FakeStore(
        edges={war.entity_id: hops},
        entities={e.entity_id: e for e in [war, *neighbours]},
    )
    doc_chunks = {f"faction_{i}": [f"faction_{i}:c0"] for i in range(5)}

    expansion = graph_expand(
        "the Purge of Blackport", store, [war, *neighbours], doc_chunks, max_chunks=2
    )
    assert len(expansion.chunk_ids) == 2


def test_lower_authority_tiers_are_spent_first() -> None:
    """When the budget bites it should drop the least authoritative route, not whichever
    the walk happened to reach last."""
    war = _entity("The Purge of Blackport", "Event")
    ballad = _entity("Ballad Source", "Faction", ["wiki/ballad.md"])
    codex = _entity("Codex Source", "Faction", ["wiki/codex.md"])
    store = FakeStore(
        edges={
            war.entity_id: [
                Hop(ballad.entity_id, "fought_in", war.entity_id, "b#row", 5),
                Hop(codex.entity_id, "fought_in", war.entity_id, "c#row", 1),
            ]
        },
        entities={e.entity_id: e for e in [war, ballad, codex]},
    )
    doc_chunks = {"ballad": ["ballad:c0"], "codex": ["codex:c0"]}

    expansion = graph_expand(
        "the Purge of Blackport", store, [war, ballad, codex], doc_chunks, max_chunks=1
    )
    assert expansion.chunk_ids == ["codex:c0"]


# -- section expansion ----------------------------------------------------


@pytest.fixture
def section_index():
    ordered = ["d1:c0", "d1:c1", "d1:c2", "d2:c0"]
    meta = {
        "d1:c0": {"doc_id": "d1", "section_path": ["Chapter 1"]},
        "d1:c1": {"doc_id": "d1", "section_path": ["Chapter 1"]},
        "d1:c2": {"doc_id": "d1", "section_path": ["Chapter 2"]},
        "d2:c0": {"doc_id": "d2", "section_path": ["Chapter 1"]},
    }
    return ordered, lambda cid: meta.get(cid, {})


def test_section_expansion_pulls_the_neighbouring_chunk(section_index) -> None:
    ordered, metadata = section_index
    expansion = section_expand(["d1:c0"], ordered, metadata)
    assert expansion.chunk_ids == ["d1:c1"]


def test_section_expansion_never_crosses_a_section_boundary(section_index) -> None:
    """Chunking never spans a section boundary, so crossing one here would undo that
    guarantee and hand the composer prose from a different subject."""
    ordered, metadata = section_index
    expansion = section_expand(["d1:c1"], ordered, metadata)
    assert "d1:c2" not in expansion.chunk_ids


def test_section_expansion_never_crosses_a_document_boundary(section_index) -> None:
    ordered, metadata = section_index
    expansion = section_expand(["d1:c2"], ordered, metadata)
    assert "d2:c0" not in expansion.chunk_ids


def test_section_expansion_cannot_add_a_new_document(section_index) -> None:
    """This is why row 5 and row 6 are separate ablation rows: section expansion is
    arithmetically incapable of improving coverage@k, which counts documents."""
    ordered, metadata = section_index
    expansion = section_expand(["d1:c0", "d1:c1"], ordered, metadata)
    reached = {metadata(c)["doc_id"] for c in expansion.chunk_ids}
    assert reached <= {"d1"}


def test_already_retrieved_chunks_are_not_re_added(section_index) -> None:
    ordered, metadata = section_index
    expansion = section_expand(["d1:c0"], ordered, metadata, exclude={"d1:c1"})
    assert expansion.chunk_ids == []


# -- helpers --------------------------------------------------------------


def test_doc_slug_translates_a_wiki_reference_to_a_document_id() -> None:
    assert doc_slug("wiki/the_purge_of_blackport.md") == "the_purge_of_blackport"


def test_build_doc_chunks_keeps_index_order() -> None:
    ordered = ["d1:c0", "d2:c0", "d1:c1"]
    meta = {"d1:c0": {"doc_id": "d1"}, "d2:c0": {"doc_id": "d2"}, "d1:c1": {"doc_id": "d1"}}
    index = build_doc_chunks(ordered, lambda cid: meta[cid])
    assert index == {"d1": ["d1:c0", "d1:c1"], "d2": ["d2:c0"]}
