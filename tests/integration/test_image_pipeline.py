"""Acceptance tests for the image pipeline, scored against the hand-authored gold set.

These are the project's first real metrics, not smoke tests. Sub-track 1A is 11 of the
20 dev questions and its answers exist only inside images, so `test_gold_recovery` is
the single number that says whether the largest block of marks is reachable.

Skipped when `data/index/images.jsonl` is absent, so a clean clone still runs green
before ingestion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.config import CORPUS_ROOT, get_settings

REPO = Path(__file__).resolve().parents[2]
SUITES = REPO / "eval" / "suites"
INDEX = get_settings().index_dir / "images.jsonl"

pytestmark = pytest.mark.skipif(
    not INDEX.exists(), reason="run `uv run python -m src.ingestion.images` first"
)


def _norm(value: object) -> str:
    """Compare answers ignoring thousands separators, case and hyphenation."""
    return str(value).lower().replace(",", "").replace("-", " ").strip()


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return [
        json.loads(line) for line in INDEX.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.fixture(scope="module")
def by_path(records) -> dict[str, dict]:
    """Every source path resolves to its record, including duplicate plate paths."""
    return {path: record for record in records for path in record["paths"]}


def _suite(name: str) -> dict:
    return json.loads((SUITES / name).read_text(encoding="utf-8"))


def _subject_value(record: dict, subject: str) -> str | None:
    """The value bound to the plate's own subject label - not merely present somewhere.

    This is the whole point of the pipeline. `plate_07` carries 55 twice: once as the
    Lantern's attunement cost and once as the Adept tolerance reference bar. Only the
    label binding distinguishes them.
    """
    target = _norm(subject)
    for entry in record.get("values") or []:
        label = _norm(entry.get("label", ""))
        if label == target or target in label or label in target:
            return str(entry.get("value", ""))
    return None


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def test_all_seventy_unique_images_described(records) -> None:
    assert len(records) == 70
    assert all(r["description"] or r["objects_depicted"] for r in records)


def test_dead_letter_is_empty() -> None:
    dead = get_settings().index_dir / "images.deadletter.jsonl"
    assert not dead.exists() or not dead.read_text(encoding="utf-8").strip()


def test_dedup_collapses_the_fifteen_duplicate_plates(records) -> None:
    """Finding 10: images/ and codex/images/ hold the same 15 plates byte-identically."""
    assert sum(len(r["paths"]) for r in records) == 85
    doubled = [r for r in records if len(r["paths"]) == 2]
    assert len(doubled) == 15
    for record in doubled:
        assert record["canonical_path"].startswith("images/"), record["canonical_path"]


def test_every_image_is_entity_linked(records) -> None:
    """Deterministic in both directions: plate filenames and wiki alt text."""
    assert all(r["entity_link"] for r in records)


def test_entity_links_resolve_against_the_graph(records) -> None:
    from src.graph.wiki_extract import extract, load_corpus_articles

    graph = extract(load_corpus_articles(CORPUS_ROOT / "wiki"))
    unresolved = sorted(
        {r["entity_link"] for r in records if r["entity_link"] not in graph.entities}
    )
    assert not unresolved, f"{len(unresolved)} dangling links, e.g. {unresolved[:5]}"


# --------------------------------------------------------------------------
# The metric that matters
# --------------------------------------------------------------------------


def test_gold_recovery_across_all_eleven_1a_questions(by_path) -> None:
    """Every 1A dev answer must be recoverable from its image's record."""
    questions = _suite("rich_1a.json")["questions"]
    missed = []
    for question in questions:
        record = by_path.get(question["gold_assets"][0])
        assert record is not None, f"{question['qid']}: no record for its gold asset"
        blob = _norm(json.dumps(record))
        accepted = [question["gold_answer"], *question["accept"]]
        if not any(_norm(candidate) in blob for candidate in accepted):
            missed.append(question["qid"])
    assert (
        not missed
    ), f"gold recovery {len(questions) - len(missed)}/{len(questions)}, missed {missed}"


@pytest.mark.parametrize("case", _suite("chart_reading.json")["cases"], ids=lambda c: c["case_id"])
def test_chart_value_is_bound_to_its_subject_label(case, by_path) -> None:
    """The answer must be the value bound to the subject, never the largest number.

    A model that merely lists every number on the plate passes gold recovery and fails
    here - which is the distinction the whole 1A path rests on.
    """
    record = by_path[case["asset"]]
    bound = _subject_value(record, case["subject"])
    assert bound is not None, f"no value bound to {case['subject']!r} in {record.get('values')}"
    assert _norm(bound) == _norm(
        case["subject_value"]
    ), f"{case['case_id']}: bound {bound!r}, expected {case['subject_value']!r}"


@pytest.mark.parametrize("case", _suite("chart_reading.json")["cases"], ids=lambda c: c["case_id"])
def test_forbidden_values_are_never_bound_to_the_subject(case, by_path) -> None:
    """Reference bars and axis endpoints must stay attached to their own labels."""
    record = by_path[case["asset"]]
    bound = _subject_value(record, case["subject"])
    forbidden = {_norm(v) for v in case["forbidden_answers"]}
    assert (
        _norm(bound) not in forbidden
    ), f"{case['case_id']}: subject bound to forbidden value {bound!r}"


def test_reference_bars_are_preserved_as_separate_entries(by_path) -> None:
    """Emberdeep is the canonical trap: all three reference standards must survive as
    their own labelled entries, so the conflict layer can show the working."""
    record = by_path["images/plate_01_location_emberdeep.png"]
    labelled = {_norm(v["label"]): _norm(v["value"]) for v in record["values"]}
    assert labelled.get("emberdeep") == "1114"
    assert "800" in labelled.values()
    assert "2400" in labelled.values()
    assert "6000" in labelled.values()


# --------------------------------------------------------------------------
# Index quality
# --------------------------------------------------------------------------


def test_searchable_text_keeps_the_label_to_value_binding(by_path) -> None:
    """Flattening values into prose would re-create the ambiguity we removed."""
    text = by_path["images/plate_01_location_emberdeep.png"]["searchable_text"]
    assert "Emberdeep: 1,114" in text or "Emberdeep: 1114" in text


def test_plates_carry_values_and_portraits_carry_objects(records) -> None:
    plates = [r for r in records if r["source_type"] == "figure_plate"]
    assert len(plates) == 15
    assert all(r["values"] for r in plates), "every plate must yield label/value pairs"

    portraits = [r for r in records if "atmo_portrait" in r["canonical_path"]]
    assert portraits
    assert all(r["objects_depicted"] for r in portraits)


def test_tiers_and_source_types_are_assigned(records) -> None:
    assert all(1 <= r["authority_tier"] <= 5 for r in records)
    assert {r["authority_tier"] for r in records} == {1, 2}
    assert all(r["source_type"] in {"figure_plate", "wiki_image"} for r in records)
