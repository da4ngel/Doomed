"""Tests for the deterministic wiki graph extractor.

The three chain tests at the bottom are the real gate. They are the actual hop paths
behind dev questions 1b_003, 1b_006 and 1b_013, so if the graph regresses, sub-track 1B
fails here rather than in a demo.
"""

from __future__ import annotations

import pytest

from src.api.schemas import Relation
from src.core.config import CORPUS_ROOT
from src.graph.wiki_extract import (
    entity_id,
    extract,
    load_corpus_articles,
    parse_article,
)

ARTICLE = """![Aldous Wrenfield](images/atmo_portrait_character_aldous_wrenfield.png)

# Aldous Wrenfield the Last Warden

Aldous commands [[Fenspire]] since 336 AS.

## Infobox

| Field | Value |
|---|---|
| Role | Reliquary Keeper |
| Born | 315 AS |
| Member of | The Iron-Ring Cartel |
| Commands | Fenspire since 336 AS |
| Wields | The Silent Psalter since 341 AS |
| Mentor of | Thessaly Coldwater |

## History

Some prose.
"""


def _relations(text: str, path: str = "wiki/x.md") -> list[Relation]:
    return extract({path: text}).relations


def test_parses_title_image_and_infobox() -> None:
    article = parse_article("wiki/x.md", ARTICLE)
    assert article.title == "Aldous Wrenfield the Last Warden"
    assert article.entity_type == "Character"
    assert article.image == "images/atmo_portrait_character_aldous_wrenfield.png"
    assert ("Born", "315 AS") in article.infobox
    assert "Fenspire" in article.wikilinks


def test_since_qualifier_is_captured_not_glued_into_the_name() -> None:
    """`Commands | Fenspire since 336 AS` is an edge to Fenspire, not to a place
    called "Fenspire since 336 AS"."""
    commands = [r for r in _relations(ARTICLE) if r.predicate == "commands"]
    assert len(commands) == 1
    assert commands[0].object_id == entity_id("Fenspire")
    assert commands[0].qualifier == "since 336 AS"


def test_wielding_since_a_year_also_emits_bore_since() -> None:
    """1b_003 walks bore_since; the infobox only ever says "Wields"."""
    predicates = {(r.predicate, r.object_id) for r in _relations(ARTICLE)}
    assert ("bore_since", entity_id("The Silent Psalter")) in predicates
    assert ("wields", entity_id("The Silent Psalter")) in predicates


def test_every_edge_carries_evidence() -> None:
    """No unsourced edges, ever."""
    for relation in _relations(ARTICLE):
        assert relation.evidence_chunk_id
        assert relation.evidence_chunk_id.startswith("wiki/x.md#")


def test_multi_valued_cells_become_separate_edges() -> None:
    text = ARTICLE.replace("| Mentor of | Thessaly Coldwater |", "| Members | A; B; C |")
    members = [r for r in _relations(text) if r.predicate == "has_member"]
    assert {r.object_id for r in members} == {entity_id("A"), entity_id("B"), entity_id("C")}


def test_inverse_fields_point_the_right_way() -> None:
    """A `Mentor` field names who mentors THIS article's subject."""
    text = ARTICLE.replace("| Mentor of | Thessaly Coldwater |", "| Mentor | Old Master |")
    mentor = next(r for r in _relations(text) if r.predicate == "mentor_of")
    assert mentor.subject_id == entity_id("Old Master")
    assert mentor.object_id == entity_id("Aldous Wrenfield the Last Warden")


def test_victor_on_an_event_article_points_from_the_winner() -> None:
    """The bug that silently broke 1b_006: `Victor` sits on the EVENT's page."""
    text = (
        "# The War of X (conflict)\n\n## Infobox\n\n"
        "| Field | Value |\n|---|---|\n| Victor | The Silent Choir |\n"
    )
    won = next(r for r in _relations(text) if r.predicate == "won")
    assert won.subject_id == entity_id("The Silent Choir")
    assert won.object_id == entity_id("The War of X")


def test_value_carried_predicate_beats_the_field_label() -> None:
    """`Outcome | Victor of X` is a won edge however the column is named."""
    text = (
        "# The Order (faction)\n\n## Infobox\n\n"
        "| Field | Value |\n|---|---|\n| Outcome | Victor of The Accord |\n"
    )
    won = next(r for r in _relations(text) if r.predicate == "won")
    assert won.subject_id == entity_id("The Order")
    assert won.object_id == entity_id("The Accord")


def test_prose_fallback_requires_a_wikilink() -> None:
    """A prose pattern can connect two names the corpus wrote down; it cannot invent
    an entity, because the object must be an explicit [[wikilink]]."""
    linked = "# Relic (artifact)\n\nThe relic is housed in [[Gloamreach]].\n"
    unlinked = "# Relic (artifact)\n\nThe relic is housed in Gloamreach.\n"
    assert any(r.predicate == "housed_at" for r in _relations(linked))
    assert not any(r.predicate == "housed_at" for r in _relations(unlinked))


# --------------------------------------------------------------------------
# Against the real corpus
# --------------------------------------------------------------------------

pytestmark_corpus = pytest.mark.skipif(not CORPUS_ROOT.exists(), reason="corpus not present")


corpus_graph_test = pytest.mark.skipif(not CORPUS_ROOT.exists(), reason="corpus not present")


@pytest.fixture(scope="module")
def graph():
    if not CORPUS_ROOT.exists():
        pytest.skip("corpus not present")
    return extract(load_corpus_articles(CORPUS_ROOT / "wiki"))


def test_corpus_extraction_is_dense_enough_to_be_useful(graph) -> None:
    assert graph.articles == 95
    assert len(graph.entities) == 198
    assert len(graph.relations) >= 350


def test_no_relational_infobox_field_is_left_unmapped(graph) -> None:
    """Finding 12: a sparse graph looks exactly like a working one, so unmapped
    fields are counted rather than dropped silently."""
    assert graph.unmapped_fields == {}, graph.unmapped_fields
    assert graph.field_coverage() == 1.0


def test_all_thirteen_predicates_are_populated(graph) -> None:
    found = {r.predicate for r in graph.relations}
    expected = {
        "member_of",
        "has_member",
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
        "housed_at",
        "secret",
    }
    assert expected <= found, expected - found


def test_every_corpus_edge_is_sourced(graph) -> None:
    assert all(r.evidence_chunk_id.startswith("wiki/") for r in graph.relations)


def _step(graph, subject: str, predicate: str) -> list[str]:
    return [
        r.object_id for r in graph.relations if r.subject_id == subject and r.predicate == predicate
    ]


def _step_back(graph, obj: str, predicate: str) -> list[str]:
    return [
        r.subject_id for r in graph.relations if r.object_id == obj and r.predicate == predicate
    ]


def test_chain_1b_006_war_to_victor_to_member(graph) -> None:
    """ "Which individual was a member of the faction that won the War of Drowned Light?"""
    winners = _step_back(graph, entity_id("The War of Drowned Light"), "won")
    assert entity_id("The Silent Choir") in winners

    members = _step(graph, entity_id("The Silent Choir"), "has_member")
    members += _step_back(graph, entity_id("The Silent Choir"), "member_of")
    assert members, "the winning faction must have at least one reachable member"


def test_chain_1b_013_creature_to_lair_to_ruler(graph) -> None:
    """ "Whose dominion encompasses the lair of the Gravemaw Wyrm?"""
    lairs = _step(graph, entity_id("Gravemaw Wyrm"), "lair_of")
    assert entity_id("Marrowwell Abbey") in lairs
    rulers = _step(graph, entity_id("Marrowwell Abbey"), "ruled_by")
    assert entity_id("The Bleeding Crown") in rulers


def test_chain_1b_003_bearer_to_relic_to_redoubt(graph) -> None:
    """ "To which redoubt must one journey to examine the relic borne by Cerys
    Sablewood since 356 AS?" Hop 2 exists only in prose, not in any infobox."""
    relics = [
        r
        for r in graph.relations
        if r.subject_id == entity_id("Cerys Sablewood the Ashen") and r.predicate == "bore_since"
    ]
    assert relics, "bearer -> relic hop missing"
    assert relics[0].object_id == entity_id("The Cinder-Wrought Aegis")
    assert relics[0].qualifier == "since 356 AS"

    housed = _step(graph, entity_id("The Cinder-Wrought Aegis"), "housed_at")
    assert entity_id("Gloamreach") in housed


def test_a_leading_article_is_not_part_of_identity() -> None:
    """The corpus writes both "The Iron-Ring Cartel" and "Iron-Ring Cartel".

    Treating them as two entities SPLITS the graph: the Purge of Blackport is won by one
    while the members belong to the other, so 1b_009's two-hop walk found a victor with
    no members.
    """
    assert entity_id("The Iron-Ring Cartel") == entity_id("Iron-Ring Cartel")
    assert entity_id("A Ballad") == entity_id("Ballad")


def test_article_merging_does_not_merge_different_names() -> None:
    """Conservative by design - a named prefix, not a similarity threshold. Broader
    fuzzy merging is what turns Greyfell Citadel into Ironfell Citadel."""
    assert entity_id("Greyfell Citadel") != entity_id("Ironfell Citadel")
    assert entity_id("The Thrice-Bound Edge") != entity_id("The Thrice-Bound Lantern")


@corpus_graph_test
def test_no_article_collisions_remain_in_the_corpus(graph) -> None:
    import re as _re

    by_norm: dict[str, list[str]] = {}
    for entity in graph.entities.values():
        key = _re.sub(r"^(the|a|an)\s+", "", entity.canonical_name.lower()).strip()
        by_norm.setdefault(key, []).append(entity.canonical_name)
    collisions = {k: v for k, v in by_norm.items() if len(v) > 1}
    assert not collisions, f"{len(collisions)} article collisions: {list(collisions)[:5]}"


@corpus_graph_test
def test_chain_1b_009_reaches_a_member_of_the_victor(graph) -> None:
    """Purge of Blackport -> victor -> member. Broken until article merging landed."""
    victors = _step_back(graph, entity_id("The Purge of Blackport"), "won")
    assert entity_id("The Iron-Ring Cartel") in victors
    members = _step(graph, entity_id("The Iron-Ring Cartel"), "has_member")
    assert entity_id("Halvard Crowhurst") in members
