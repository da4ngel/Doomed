"""Validate the hand-authored gold suites against the real corpus.

WHY this test exists: a gold label pointing at a path that does not exist produces a
metric that silently measures nothing. Every number in the report descends from these
files, so they are verified against the corpus rather than trusted.

Skipped when the corpus is absent, so a clean clone without `data/corpus/` still has a
green test run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.config import CORPUS_ROOT

SUITES = Path(__file__).resolve().parents[2] / "eval" / "suites"

pytestmark = pytest.mark.skipif(
    not CORPUS_ROOT.exists(), reason="corpus not present; unzip data/corpus first"
)


def _load(name: str) -> dict:
    return json.loads((SUITES / name).read_text(encoding="utf-8"))


def _dev_questions() -> dict[str, str]:
    raw = json.loads((CORPUS_ROOT / "sample_questions.json").read_text(encoding="utf-8"))
    return {q["qid"]: q["question"] for q in raw}


def test_rich_1a_covers_every_1a_dev_question() -> None:
    raw = json.loads((CORPUS_ROOT / "sample_questions.json").read_text(encoding="utf-8"))
    expected = {q["qid"] for q in raw if q["track"].startswith("1A")}
    got = {q["qid"] for q in _load("rich_1a.json")["questions"]}
    assert got == expected, f"missing: {expected - got}, extra: {got - expected}"


def test_gold_questions_match_the_dev_set_verbatim() -> None:
    """A paraphrased question would quietly change what we are measuring."""
    dev = _dev_questions()
    for question in _load("rich_1a.json")["questions"]:
        # The dev file uses a typographic apostrophe; compare on a normalised form.
        expected = dev[question["qid"]].replace("’", "'")
        assert question["question"].replace("’", "'") == expected, question["qid"]


def test_every_gold_asset_exists() -> None:
    for question in _load("rich_1a.json")["questions"]:
        for asset in question["gold_assets"] + question["duplicate_assets"]:
            assert (CORPUS_ROOT / asset).exists(), f"{question['qid']}: missing {asset}"


def test_every_gold_doc_exists() -> None:
    for question in _load("rich_1a.json")["questions"]:
        for doc in question["gold_docs"]:
            assert (CORPUS_ROOT / doc).exists(), f"{question['qid']}: missing {doc}"


def test_declared_duplicates_are_byte_identical() -> None:
    """Finding 10: images/ and codex/images/ hold the same 15 plates."""
    import hashlib

    for question in _load("rich_1a.json")["questions"]:
        for original in question["gold_assets"]:
            for duplicate in question["duplicate_assets"]:
                a = hashlib.sha256((CORPUS_ROOT / original).read_bytes()).hexdigest()
                b = hashlib.sha256((CORPUS_ROOT / duplicate).read_bytes()).hexdigest()
                assert a == b, f"{question['qid']}: {duplicate} is not a duplicate"


def test_gold_answer_is_always_an_accepted_form() -> None:
    for question in _load("rich_1a.json")["questions"]:
        normalised = {a.lower().replace(",", "") for a in question["accept"]}
        answer = question["gold_answer"].lower().replace(",", "")
        assert any(answer in a or a in answer for a in normalised), question["qid"]


def test_chart_cases_never_allow_the_subject_value_as_forbidden() -> None:
    """A self-contradicting case would fail every run for the wrong reason."""
    for case in _load("chart_reading.json")["cases"]:
        assert case["subject_value"] not in case["forbidden_answers"], case["case_id"]


def test_chart_forbidden_answers_are_the_distractors_actually_on_the_plate() -> None:
    """Each forbidden value must be a reference value or a named cross-plate decoy."""
    cross_plate = {"94", "None recorded"}
    for case in _load("chart_reading.json")["cases"]:
        on_plate = {r["value"] for r in case["reference_values"]}
        for forbidden in case["forbidden_answers"]:
            assert forbidden in on_plate | cross_plate, f"{case['case_id']}: {forbidden}"


def test_chart_reading_covers_three_figure_grammars() -> None:
    """Finding 9: a fix must not pass by special-casing one layout."""
    grammars = {c["figure_grammar"] for c in _load("chart_reading.json")["cases"]}
    assert grammars == {
        "bar_chart_with_reference_bars",
        "gauge",
        "single_value_plate",
    }


def test_chart_cases_reference_a_gold_question() -> None:
    known = {q["qid"] for q in _load("rich_1a.json")["questions"]}
    for case in _load("chart_reading.json")["cases"]:
        assert case["qid"] in known, case["case_id"]
        assert (CORPUS_ROOT / case["asset"]).exists(), case["case_id"]
