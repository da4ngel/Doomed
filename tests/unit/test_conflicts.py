"""Tests for A4 conflict detection.

The corpus tests at the bottom are the gate: both 1C dev answers must fall out of this
layer, resolved by tier, against the real index.

Several tests here exist because the first implementation FAILED them. It attributed
each attribute to the longest entity name anywhere in the chunk and invented conflicts
wholesale - a founding year for a swordsman, a forging year scraped from an unrelated
sentence - while missing both real ones. An invented disagreement is worse than a missed
one, so those cases are pinned.
"""

from __future__ import annotations

import json

import pytest

from src.api.schemas import Chunk
from src.core.config import get_settings
from src.synthesis.conflicts import (
    detect_conflicts,
    extract_assertions,
    is_absence_claim,
    normalise_value,
)

INDEX = get_settings().index_dir

TYPED = {
    "Gloamreach": "Location",
    "Blackford": "Location",
    "Cindermere Hold": "Location",
    "The Thrice-Bound Edge": "Artifact",
    "Gauntlet of Sorrowfell": "Artifact",
    "Brannoc Ironmere the Red-Handed": "Character",
    "Weeping Lurker": "Component",
}


def _chunk(text: str, tier: int = 2, doc: str = "d", section=None, cid: str = "c1") -> Chunk:
    return Chunk(
        chunk_id=cid,
        doc_id=doc,
        text=text,
        authority_tier=tier,
        source_type="wiki",
        section_path=section or [],
    )


# --------------------------------------------------------------------------
# value normalisation
# --------------------------------------------------------------------------


def test_thousands_separators_are_not_a_disagreement() -> None:
    assert normalise_value("1,114") == normalise_value("1114")


def test_a_unit_suffix_is_not_a_disagreement() -> None:
    """ "4672 troops" and "4672" are one claim. Reporting the unit as a conflict is
    reporting formatting, which is what this layer must never do."""
    assert normalise_value("4672 troops") == normalise_value("4672")


def test_year_spacing_is_normalised() -> None:
    assert normalise_value("391  AS") == normalise_value("391 AS") == "391 AS"


def test_absence_phrasings_collapse_to_one_claim() -> None:
    """Two phrasings clustered separately produced a conflict between a claim and
    itself - 'none recorded' versus 'none recorded'."""
    assert is_absence_claim("None recorded")
    assert is_absence_claim("no attunement cost")
    assert is_absence_claim("")
    assert not is_absence_claim("94")


# --------------------------------------------------------------------------
# attribution
# --------------------------------------------------------------------------


def test_a_character_is_never_given_a_founding_year() -> None:
    """The type gate. A novel chunk naming a swordsman and a year produced
    "Brannoc Ironmere the Red-Handed founding year" before this existed."""
    text = "Brannoc Ironmere the Red-Handed rode out. The hold was founded in 57 AS."
    found = extract_assertions(
        _chunk(text, tier=3), {"Brannoc Ironmere the Red-Handed": "Character"}
    )
    assert found == []


def test_an_artifact_is_never_given_a_founding_year() -> None:
    text = "Gauntlet of Sorrowfell lay there. The city was founded in 321 AS."
    found = extract_assertions(_chunk(text), {"Gauntlet of Sorrowfell": "Artifact"})
    assert not any(a.attribute == "founding year" for a in found)


def test_a_flat_record_attributes_each_value_to_its_own_entry() -> None:
    """The codex gazetteer is a run of records in one chunk. Taking the section heading
    gave every value to the first entry and manufactured a conflict between two places."""
    text = (
        "Blackford\n| Field | Value |\n|---|---|\n| Founded | 159 AS |\n\n"
        "Cindermere Hold\n| Field | Value |\n|---|---|\n| Founded | 246 AS |\n"
    )
    found = extract_assertions(_chunk(text, tier=1, section=["Blackford"]), TYPED)
    by_entity = {a.entity: a.value for a in found if a.attribute == "founding year"}
    assert by_entity.get("Blackford") == "159 AS"
    assert by_entity.get("Cindermere Hold") == "246 AS"


def test_an_infobox_row_is_attributed_to_its_article_subject() -> None:
    text = "Gloamreach\n\n| Field | Value |\n|---|---|\n| Founded | 246 AS |"
    found = extract_assertions(_chunk(text, tier=1, section=["Gloamreach"]), TYPED)
    assert any(a.entity == "Gloamreach" and a.value == "246 AS" for a in found)


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------


def _conflicts(chunks):
    return detect_conflicts(chunks, TYPED).conflicts


def test_a_higher_tier_wins_and_says_why() -> None:
    chunks = [
        _chunk("Gloamreach was founded in 246 AS.", tier=1, doc="codex", cid="a"),
        _chunk("Gloamreach was founded in 286 AS.", tier=4, doc="contract", cid="b"),
    ]
    conflict = _conflicts(chunks)[0]
    assert conflict.claim_a == "246 AS"
    assert conflict.tier_a == 1
    assert conflict.resolution == "higher_tier"
    assert "tier 4" in conflict.rationale.lower()


def test_equal_tiers_refuse_to_resolve() -> None:
    """Refusing is the feature. A mis-resolved conflict is a fabrication with two real
    citations attached."""
    chunks = [
        _chunk("Gloamreach was founded in 246 AS.", tier=4, doc="one", cid="a"),
        _chunk("Gloamreach was founded in 286 AS.", tier=4, doc="two", cid="b"),
    ]
    conflict = _conflicts(chunks)[0]
    assert conflict.resolution == "unresolved"
    assert conflict.claim_a and conflict.claim_b


def test_two_tier_one_sources_agreeing_beat_a_lone_tier_one() -> None:
    chunks = [
        _chunk("Gloamreach was founded in 246 AS.", tier=1, doc="codex", cid="a"),
        _chunk("Gloamreach was founded in 246 AS.", tier=1, doc="annals", cid="b"),
        _chunk("Gloamreach was founded in 286 AS.", tier=4, doc="contract", cid="c"),
    ]
    conflict = _conflicts(chunks)[0]
    assert conflict.resolution == "tier_1_corroborated"
    assert len(conflict.sources_a) == 2


def test_agreement_is_not_reported_as_a_conflict() -> None:
    chunks = [
        _chunk("Gloamreach was founded in 246 AS.", tier=1, doc="codex", cid="a"),
        _chunk("Gloamreach was founded in 246 AS.", tier=4, doc="letter", cid="b"),
    ]
    assert _conflicts(chunks) == []


def test_duplicate_chunks_do_not_manufacture_corroboration() -> None:
    """The same chunk twice is one source, not two - the same inflation that made
    indexing format twins dangerous."""
    chunk = _chunk("Gloamreach was founded in 246 AS.", tier=1, doc="codex", cid="same")
    report = detect_conflicts([chunk, chunk], TYPED)
    assert len({a.chunk_id for a in report.assertions}) == 1


# --------------------------------------------------------------------------
# against the real corpus
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# one asset is one source, however many extractors read it
# --------------------------------------------------------------------------

#: The real indexed text of plate_11_location_mournwatch.png. Direct inspection of
#: the image confirms 8,254; the gauge maximum is 9,904.
PLATE_11 = """Plate 11 - Mournwatch (location)
Subject: Mournwatch recorded garrison strength
A decorative gauge plate titled 'Mournwatch' displaying a semicircular gauge for the
recorded garrison strength. The needle-less dial is filled from 0 to the reading of
8,254 out of a maximum of 9,904 souls under arms.
Recorded values:
  Mournwatch garrison strength: 8,254
  minimum: 0
  maximum: 9,904
Depicted: semicircular gauge arc, filled arc segment, numerical readout
Text in image: Mournwatch
RECORDED GARRISON STRENGTH
8,254
0
9,904
souls under arms"""

MOURNWATCH_PNG = "images/plate_11_location_mournwatch.png"


def _plate_chunk(text: str, cid: str) -> Chunk:
    return Chunk(
        chunk_id=cid,
        doc_id=MOURNWATCH_PNG,
        text=text,
        authority_tier=1,
        source_type="figure_plate",
        section_path=[],
    )


def test_ocr_and_vlm_reading_one_plate_are_not_two_sources() -> None:
    """Reported against a build with Tesseract installed, which this machine lacks.

    The vision model reads 8,254 off the gauge and OCR misreads it as 6,254. With OCR
    text appended the image chunk splits, so the two readings land in two chunks of
    the SAME png - and the old code emitted a tier-1 Conflict naming that one file on
    both sides. An archive contradicting itself, which the archive never did.

    An invented disagreement is worse than a missed one, and the 1C answers are built
    out of exactly this layer.
    """
    chunks = [
        _plate_chunk(PLATE_11, "img:mournwatch#0"),
        _plate_chunk(PLATE_11.replace("8,254", "6,254"), "img:mournwatch#1"),
    ]
    report = detect_conflicts(chunks, {"Mournwatch": "Location"})

    for conflict in report.conflicts:
        assert set(conflict.sources_a) != set(
            conflict.sources_b
        ), f"{conflict.attribute} names {MOURNWATCH_PNG} on both sides"


def test_the_extraction_disagreement_is_kept_for_audit() -> None:
    """Suppressed as a conflict, not discarded. A plate whose two readers disagree is
    worth knowing about; it is just not evidence about the world."""
    chunks = [
        _plate_chunk(PLATE_11, "img:mournwatch#0"),
        _plate_chunk(PLATE_11.replace("8,254", "6,254"), "img:mournwatch#1"),
    ]
    report = detect_conflicts(chunks, {"Mournwatch": "Location"})

    assert report.extraction_disagreements, "the disagreement must survive for audit"
    note = report.extraction_disagreements[0]
    assert "same image" in note
    assert "plate_11_location_mournwatch" in note
    assert "8254" in note and "6254" in note


def test_two_different_documents_still_conflict_normally() -> None:
    """The guard must be narrow. Two real documents disagreeing is the feature."""
    chunks = [
        _chunk("Gloamreach was founded in 812 AS.", tier=1, doc="codex/a", cid="c1"),
        _chunk("Gloamreach was founded in 907 AS.", tier=3, doc="chronicles/b", cid="c2"),
    ]
    report = detect_conflicts(chunks, {"Gloamreach": "Location"})
    assert report.conflicts, "a genuine two-document disagreement must survive"
    assert set(report.conflicts[0].sources_a) != set(report.conflicts[0].sources_b)


indexed = pytest.mark.skipif(
    not (INDEX / "chunks.jsonl").exists() or not (INDEX / "graph.sqlite").exists(),
    reason="index not built",
)


@pytest.fixture(scope="module")
def corpus_report():
    if not (INDEX / "chunks.jsonl").exists():
        pytest.skip("index not built")
    from src.graph.store import GraphStore

    chunks = [
        Chunk(**json.loads(line))
        for line in (INDEX / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _, entities = GraphStore(INDEX / "graph.sqlite").all_entities(limit=1000)
    typed = {e.canonical_name: e.type for e in entities if e.type != "Title"}
    return detect_conflicts(chunks, typed)


@indexed
def test_1c_000_gloamreach_resolves_to_the_gold_answer(corpus_report) -> None:
    """246 AS from the tier-1 codex, against 286 AS in a tier-4 contract."""
    match = next(
        (c for c in corpus_report.conflicts if c.attribute == "Gloamreach founding year"),
        None,
    )
    assert match is not None, "the Gloamreach conflict was not detected"
    assert match.claim_a == "246 AS"
    assert match.tier_a == 1
    assert match.tier_b > 1
    assert match.resolution in {"higher_tier", "tier_1_corroborated"}


@indexed
def test_1c_003_gauntlet_resolves_to_the_gold_answer(corpus_report) -> None:
    """391 AS from the tier-1 codex, against 360 AS in a tier-5 sermon - exactly the
    folkloric case the authority table was designed for."""
    match = next(
        (
            c
            for c in corpus_report.conflicts
            if c.attribute == "Gauntlet of Sorrowfell forging year"
        ),
        None,
    )
    assert match is not None, "the Gauntlet conflict was not detected"
    assert match.claim_a == "391 AS"
    assert match.tier_a == 1
    assert match.tier_b == 5
    assert "folkloric" in match.rationale.lower()


@indexed
def test_no_conflict_pairs_a_claim_with_itself(corpus_report) -> None:
    """'none recorded' versus 'none recorded' was reported as a disagreement."""
    for conflict in corpus_report.conflicts:
        assert conflict.claim_a != conflict.claim_b, conflict.attribute


@indexed
def test_every_conflict_names_two_real_sources(corpus_report) -> None:
    for conflict in corpus_report.conflicts:
        assert conflict.sources_a and conflict.sources_b
        assert (
            set(conflict.sources_a) != set(conflict.sources_b) or conflict.tier_a != conflict.tier_b
        )


@indexed
def test_attribute_types_always_agree_with_their_entity(corpus_report) -> None:
    """No characters with founding years. The first version produced several."""
    from src.graph.store import GraphStore

    _, entities = GraphStore(INDEX / "graph.sqlite").all_entities(limit=1000)
    typed = {e.canonical_name: e.type for e in entities}
    allowed = {
        "founding year": {"Location"},
        "garrison strength": {"Location"},
        "forging year": {"Artifact"},
        "attunement cost": {"Artifact"},
        "threat rating": {"Component"},
    }
    for conflict in corpus_report.conflicts:
        for attribute, kinds in allowed.items():
            if conflict.attribute.endswith(attribute):
                entity = conflict.attribute[: -len(attribute)].strip()
                assert typed.get(entity) in kinds, f"{entity} cannot have a {attribute}"


@indexed
def test_the_conflict_count_stays_small_and_reviewable(corpus_report) -> None:
    """Every conflict must be checkable by opening two documents. A layer emitting
    dozens is inventing them - the first version emitted noise across the whole corpus."""
    assert 2 <= len(corpus_report.conflicts) <= 20, len(corpus_report.conflicts)
