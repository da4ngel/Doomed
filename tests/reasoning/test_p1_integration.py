"""Exercise P1's actual detector/endpoint ABI with explicit source fixtures."""

import json
from pathlib import Path

import pytest

from src.agents.analyst import QueryAnalyst
from src.agents.conflict_adapter import ConflictAdapter, Vocabulary
from src.agents.merger import merge_evidence
from src.api.schemas import Entity, SearchHit


def hit(text, tier, doc, entity):
    return SearchHit(
        chunk_id=f"{doc}:c1",
        doc_id=doc,
        title=doc,
        text=text,
        score=1,
        page=7,
        section_path=[entity],
        authority_tier=tier,
        source_type="codex",
    )


@pytest.mark.parametrize(
    ("name", "kind", "attribute", "text_a", "text_b", "expected"),
    [
        (
            "Gloamreach",
            "Location",
            "founding year",
            "Gloamreach was founded in 246 AS.",
            "Gloamreach was founded in 286 AS.",
            "246 AS",
        ),
        (
            "Gauntlet of Sorrowfell",
            "Artifact",
            "forging year",
            "Gauntlet of Sorrowfell's forged is 391 AS.",
            "Gauntlet of Sorrowfell forged year is 360 AS.",
            "391 AS",
        ),
        (
            "The Thrice-Bound Edge",
            "Artifact",
            "attunement cost",
            "The Thrice-Bound Edge\nAttunement Cost: 94 vitae-grains",
            "The Thrice-Bound Edge\n| Attunement cost | None recorded |",
            "94",
        ),
    ],
)
def test_real_p1_detector_connected(name, kind, attribute, text_a, text_b, expected):
    entity = Entity(entity_id="e", canonical_name=name, type=kind)
    vocabulary = Vocabulary(lambda: {"total": 1, "entities": [entity.model_dump()]})
    first, second = hit(text_a, 1, "codex", name), hit(text_b, 5, "ballad", name)
    before = [first.model_dump(), second.model_dump()]
    result = merge_evidence([first, second], detector=ConflictAdapter(vocabulary))
    assert not result.warnings
    (conflict,) = result.conflicts
    assert conflict.attribute == f"{name} {attribute}"
    assert conflict.claim_a == expected
    assert conflict.sources_a == ["codex"] and conflict.sources_b == ["ballad"]
    assert conflict.resolution == "higher_tier"
    assert before == [first.model_dump(), second.model_dump()]


def test_missing_types_never_claims_a4_succeeded():
    result = merge_evidence([], detector=ConflictAdapter(lambda: []))
    assert result.warnings[0].action == "conflict_detection_unavailable"


def test_complete_vocabulary_is_shared_and_title_literals_are_excluded():
    calls = []
    rows = [
        Entity(entity_id="g", canonical_name="Gloamreach", type="Location").model_dump(),
        Entity(entity_id="lit", canonical_name="Neverland", type="Title").model_dump(),
    ]

    def fetch():
        calls.append(1)
        return {"total": 2, "entities": rows}

    vocabulary = Vocabulary(fetch)
    analyst = QueryAnalyst(vocabulary_loader=vocabulary)
    assert analyst.analyze("Gloamreach").seed_entities[0].entity_id == "g"
    assert analyst.analyze("Neverland").seed_entities == []
    ConflictAdapter(vocabulary)(
        [hit("Gloamreach was founded in 246 AS.", 1, "codex", "Gloamreach")]
    )
    assert len(calls) == 1


def test_truncated_vocabulary_is_not_used_for_guessing():
    vocab = Vocabulary(lambda: {"total": 203, "entities": []})
    with pytest.raises(ValueError, match="truncated"):
        vocab()
    result = QueryAnalyst(vocabulary_loader=vocab).analyze("Greyfel Citadell")
    assert result.normalized == "Greyfel Citadell"
    assert result.warnings == ["normalization_skipped"]


def test_unicode_alias_linking_preserves_user_wording():
    entity = Entity(entity_id="edge", canonical_name="The Thrice-Bound Edge", type="Artifact")
    question = "What is the attunement cost of the “Thrice‑Bound Edge”?"
    result = QueryAnalyst(vocabulary_loader=lambda: [entity]).analyze(question)
    assert result.normalized == question
    assert result.corrections == []
    assert result.seed_entities[0].entity_id == "edge"


def test_all_twenty_checked_in_dev_texts_are_preserved():
    suites = Path(__file__).resolve().parents[2] / "eval/suites"
    rows = [
        row
        for name in ["rich_1a", "multihop_1b", "contradiction_1c"]
        for row in json.loads((suites / f"{name}.json").read_text())["questions"]
    ]
    assert len(rows) == 20
    analyst = QueryAnalyst(vocabulary_loader=lambda: [])
    for row in rows:
        result = analyst.analyze(row["question"])
        assert result.normalized == row["question"]
        assert result.sub_questions
        if row["qid"].startswith("1c_"):
            assert result.intent == "contradiction"
