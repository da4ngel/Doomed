"""Validate the 1B and 1C gold labels against the corpus and the graph.

Gold that points at a document which does not exist, or a hop chain the graph cannot
walk, produces a metric that silently measures nothing. Every number in the report
descends from these files, so they are checked rather than trusted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.config import CORPUS_ROOT, get_settings
from src.graph.store import GraphStore
from src.graph.wiki_extract import entity_id

SUITES = Path(__file__).resolve().parents[2] / "eval" / "suites"
INDEX = get_settings().index_dir

corpus = pytest.mark.skipif(not CORPUS_ROOT.exists(), reason="corpus not present")
indexed = pytest.mark.skipif(
    not (INDEX / "chunks.jsonl").exists(), reason="index not built"
)


def _suite(name: str) -> dict:
    return json.loads((SUITES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def known_doc_ids() -> set[str]:
    path = INDEX / "documents.jsonl"
    if not path.exists():
        pytest.skip("index not built")
    return {
        json.loads(line)["doc_id"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


@pytest.fixture(scope="module")
def graph() -> GraphStore:
    if not (INDEX / "graph.sqlite").exists():
        pytest.skip("graph not built")
    return GraphStore(INDEX / "graph.sqlite")


@pytest.fixture(scope="module")
def chunks() -> list[dict]:
    path = INDEX / "chunks.jsonl"
    if not path.exists():
        pytest.skip("index not built")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------
# coverage of the dev set
# --------------------------------------------------------------------------


@corpus
def test_every_dev_question_now_has_gold() -> None:
    """20 dev questions, 20 gold labels across three suites."""
    dev = json.loads((CORPUS_ROOT / "sample_questions.json").read_text(encoding="utf-8"))
    labelled = set()
    for name in ("rich_1a.json", "multihop_1b.json", "contradiction_1c.json"):
        labelled |= {q["qid"] for q in _suite(name)["questions"]}
    missing = {q["qid"] for q in dev} - labelled
    assert not missing, f"unlabelled dev questions: {sorted(missing)}"


@corpus
def test_gold_questions_match_the_dev_set_verbatim() -> None:
    """A paraphrase would quietly change what we are measuring."""
    dev = {
        q["qid"]: q["question"].replace("’", "'")
        for q in json.loads((CORPUS_ROOT / "sample_questions.json").read_text(encoding="utf-8"))
    }
    for name in ("multihop_1b.json", "contradiction_1c.json"):
        for question in _suite(name)["questions"]:
            assert question["question"].replace("’", "'") == dev[question["qid"]], question["qid"]


# --------------------------------------------------------------------------
# 1B
# --------------------------------------------------------------------------


@indexed
def test_1b_gold_documents_exist(known_doc_ids) -> None:
    for question in _suite("multihop_1b.json")["questions"]:
        for doc in question["gold_docs"]:
            assert doc in known_doc_ids, f"{question['qid']}: unknown doc_id {doc!r}"


@indexed
def test_every_1b_question_needs_more_than_one_document() -> None:
    """If one document sufficed it would not be a multi-hop question, and coverage@k
    would be measuring nothing."""
    for question in _suite("multihop_1b.json")["questions"]:
        assert len(question["gold_docs"]) >= 2, question["qid"]
        assert question["hops"] >= 2, question["qid"]


@indexed
def test_1b_hop_chains_walk_in_the_real_graph(graph) -> None:
    """The chain in the gold label must be traversable, or the label is aspirational."""
    checks = [
        ("1b_013", "Gravemaw Wyrm", "lair_of", "Marrowwell Abbey"),
        ("1b_013", "Marrowwell Abbey", "ruled_by", "The Bleeding Crown"),
        ("1b_003", "Cerys Sablewood the Ashen", "bore_since", "The Cinder-Wrought Aegis"),
        ("1b_003", "The Cinder-Wrought Aegis", "housed_at", "Gloamreach"),
        ("1b_005", "Isolde Mournvale", "member_of", "The Silent Choir"),
        ("1b_022", "Ravena Stormwell", "member_of", "The Silent Choir"),
        ("1b_007", "Ederon Fellgard", "member_of", "The Iron-Ring Cartel"),
        ("1b_007", "The Iron-Ring Cartel", "won", "The Leaden Accord"),
        ("1b_009", "The Iron-Ring Cartel", "has_member", "Halvard Crowhurst"),
    ]
    for qid, subject, predicate, obj in checks:
        edges = [
            h
            for h in graph._edges_from(entity_id(subject))  # noqa: SLF001
            if h.predicate == predicate
            and h.subject_id == entity_id(subject)
            and h.object_id == entity_id(obj)
        ]
        assert edges, f"{qid}: {subject} -{predicate}-> {obj} not in the graph"


@indexed
def test_1b_victors_are_reachable_backwards(graph) -> None:
    """"Who won X" walks the `won` edge from object to subject."""
    for war, victor in [
        ("The War of Drowned Light", "The Silent Choir"),
        ("The Purge of Blackport", "The Iron-Ring Cartel"),
    ]:
        winners = [
            h.subject_id
            for h in graph._edges_from(entity_id(war))  # noqa: SLF001
            if h.predicate == "won" and h.object_id == entity_id(war)
        ]
        assert entity_id(victor) in winners, f"{victor} not recorded as winning {war}"


@indexed
def test_1b_007_distractor_is_genuinely_present(graph) -> None:
    """The Iron-Ring Cartel won two events; 'accord' is the disambiguator. If only one
    victory existed the trap would not be real and the label would overstate it."""
    victories = {
        h.object_id
        for h in graph._edges_from(entity_id("The Iron-Ring Cartel"))  # noqa: SLF001
        if h.predicate == "won" and h.subject_id == entity_id("The Iron-Ring Cartel")
    }
    assert entity_id("The Leaden Accord") in victories
    assert entity_id("The Winter Reckoning") in victories


# --------------------------------------------------------------------------
# 1C
# --------------------------------------------------------------------------


@indexed
def test_1c_gold_documents_exist(known_doc_ids) -> None:
    for question in _suite("contradiction_1c.json")["questions"]:
        for doc in question["gold_docs"] + question["supporting_docs"]:
            assert doc in known_doc_ids, f"{question['qid']}: unknown doc_id {doc!r}"


@indexed
def test_1c_competing_claims_are_really_in_the_corpus(chunks) -> None:
    """Each claimed year must appear in a chunk from the document credited with it.

    A fabricated conflict would make the conflict layer look like it works.
    """
    by_doc: dict[str, str] = {}
    for chunk in chunks:
        by_doc[chunk["doc_id"]] = by_doc.get(chunk["doc_id"], "") + " " + chunk["text"]

    for question in _suite("contradiction_1c.json")["questions"]:
        for claim in question["competing_claims"]:
            text = by_doc.get(claim["doc_id"], "")
            year = claim["value"].split()[0]
            assert year in text, f"{question['qid']}: {year} not found in {claim['doc_id']}"


@indexed
def test_1c_answers_come_from_the_highest_tier_source(chunks) -> None:
    """The resolution is by authority tier, so the gold answer must sit at tier 1 and
    every competing claim must sit lower."""
    tiers = {c["doc_id"]: c["authority_tier"] for c in chunks}
    for question in _suite("contradiction_1c.json")["questions"]:
        gold_doc = question["gold_docs"][0]
        assert tiers[gold_doc] == 1, f"{question['qid']}: gold source is not tier 1"

        winning = [c for c in question["competing_claims"] if c["value"] == question["gold_answer"]]
        assert winning, f"{question['qid']}: gold answer is not among the competing claims"
        assert winning[0]["tier"] == 1

        losing = [c for c in question["competing_claims"] if c["value"] != question["gold_answer"]]
        assert losing, f"{question['qid']}: a contradiction question needs a competitor"
        assert all(c["tier"] > 1 for c in losing)


@indexed
def test_1c_cannot_be_answered_in_one_lookup(chunks) -> None:
    """1c_000's most obvious source refuses to give a year - the wiki says 'Contested;
    consult the Annals and Codex'. That is what makes it an iterative question."""
    wiki = " ".join(c["text"] for c in chunks if c["doc_id"] == "gloamreach")
    assert "Contested" in wiki
    assert "246" not in wiki, "if the wiki gave the answer this would be a single lookup"
