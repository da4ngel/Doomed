"""Tests for the persisted entity graph.

The three chain tests are sub-track 1B's acceptance criteria, walked from SQLite rather
than from memory - the graph has to survive storage for `/v1/graph/*` to mean anything.
"""

from __future__ import annotations

import pytest

from src.api.schemas import Entity, Relation
from src.core.config import CORPUS_ROOT, get_settings
from src.graph.store import GraphStore, build
from src.graph.wiki_extract import entity_id

corpus = pytest.mark.skipif(not CORPUS_ROOT.exists(), reason="corpus not present")


@pytest.fixture()
def store(tmp_path) -> GraphStore:
    graph = GraphStore(tmp_path / "g.sqlite")
    entities = {
        eid: Entity(entity_id=eid, canonical_name=name, type=kind)
        for eid, name, kind in [
            ("e_war", "The War", "Event"),
            ("e_faction", "The Choir", "Faction"),
            ("e_person", "Tamsin", "Character"),
        ]
    }
    relations = [
        Relation(
            subject_id="e_faction",
            predicate="won",
            object_id="e_war",
            evidence_chunk_id="wiki/war.md#infobox:Victor",
            authority_tier=2,
        ),
        Relation(
            subject_id="e_faction",
            predicate="has_member",
            object_id="e_person",
            evidence_chunk_id="wiki/choir.md#infobox:Members",
            authority_tier=2,
        ),
    ]
    graph.replace_all(entities, relations)
    return graph


def test_roundtrip_preserves_counts(store: GraphStore) -> None:
    assert store.counts() == (3, 2)


def test_evidence_and_tier_survive_storage(store: GraphStore) -> None:
    """An edge that cannot name its source is not evidence, so this must not be lost."""
    _, edges = store.neighbors("e_faction", hops=1)
    assert edges
    for hop in edges:
        assert hop.evidence_chunk_id
        assert 1 <= hop.authority_tier <= 5


def test_traversal_follows_edges_backwards(store: GraphStore) -> None:
    """ "Who won the war" walks a `won` edge from object to subject."""
    reached, _ = store.neighbors("e_war", hops=1)
    assert "e_faction" in reached


def test_two_hop_reaches_the_member_through_the_faction(store: GraphStore) -> None:
    reached, _ = store.neighbors("e_war", hops=2)
    assert "e_person" in reached


def test_hop_limit_is_respected(store: GraphStore) -> None:
    reached, _ = store.neighbors("e_war", hops=1)
    assert "e_person" not in reached


def test_rebuild_is_idempotent(store: GraphStore) -> None:
    entities = {"e_war": Entity(entity_id="e_war", canonical_name="The War", type="Event")}
    store.replace_all(entities, [])
    assert store.counts() == (1, 0)


def test_lookup_is_exact_and_never_fuzzy(store: GraphStore) -> None:
    """Fuzzy-matching invented proper nouns returns a wrong number with a real citation
    - `greyfell_citadel` vs `ironfell_citadel` (addendum, Finding 13)."""
    assert store.find_entities("The Choir")
    assert store.find_entities("the choir"), "case-insensitive is fine"
    assert not store.find_entities("The Choi"), "but a near miss must NOT match"


# --------------------------------------------------------------------------
# Against the real graph
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus_graph():
    if not CORPUS_ROOT.exists():
        pytest.skip("corpus not present")
    build(get_settings())
    return GraphStore(get_settings().index_dir / "graph.sqlite")


@corpus
def test_the_whole_wiki_graph_persists(corpus_graph) -> None:
    entities, relations = corpus_graph.counts()
    assert entities == 203
    assert relations == 379


@corpus
def test_chain_1b_013_walks_from_sqlite(corpus_graph) -> None:
    """Whose dominion encompasses the lair of the Gravemaw Wyrm?"""
    paths = corpus_graph.distinct_paths(
        entity_id("Gravemaw Wyrm"), entity_id("The Bleeding Crown"), max_hops=3
    )
    assert paths
    chain, evidence = paths[0]
    assert [h.predicate for h in chain] == ["lair_of", "ruled_by"]
    assert all(evidence)


@corpus
def test_chain_1b_003_carries_its_since_qualifier(corpus_graph) -> None:
    """To which redoubt must one journey to examine the relic borne by Cerys Sablewood
    since 356 AS? The qualifier is part of the question, so it must survive."""
    paths = corpus_graph.distinct_paths(
        entity_id("Cerys Sablewood the Ashen"), entity_id("Gloamreach"), max_hops=3
    )
    assert paths
    qualifiers = [h.qualifier for chain, _ in paths for h in chain if h.qualifier]
    assert any("356" in q for q in qualifiers)


@corpus
def test_chain_1b_006_finds_members_of_the_victor(corpus_graph) -> None:
    """Which individual was a member of the faction that won the War of Drowned Light?"""
    reached, edges = corpus_graph.neighbors(entity_id("The War of Drowned Light"), hops=2)
    assert entity_id("The Silent Choir") in reached
    assert any(h.predicate == "won" for h in edges)
    assert any(h.predicate in {"has_member", "member_of"} for h in edges)


@corpus
def test_the_same_chain_attested_twice_is_one_path(corpus_graph) -> None:
    """Corroboration must not be counted as independent routes - the same inflation
    that made indexing format twins dangerous."""
    raw = corpus_graph.paths(
        entity_id("Gravemaw Wyrm"), entity_id("The Bleeding Crown"), max_hops=3
    )
    distinct = corpus_graph.distinct_paths(
        entity_id("Gravemaw Wyrm"), entity_id("The Bleeding Crown"), max_hops=3
    )
    assert len(raw) > len(distinct), "the raw walk finds the chain more than once"
    assert len(distinct) == 1
    _, evidence = distinct[0]
    assert len(evidence) > 2, "and both attestations are kept as evidence"


@corpus
def test_networkx_load_matches_sqlite(corpus_graph) -> None:
    graph = corpus_graph.to_networkx()
    entities, relations = corpus_graph.counts()
    assert graph.number_of_nodes() == entities
    assert graph.number_of_edges() <= relations  # parallel edges collapse on (u, v, key)
