"""A1 acceptance and adversarial regressions, without upstream imports or credentials."""

import json
import os
import time
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from src.agents.analyst import Analysis, QueryAnalyst
from src.api.schemas import Entity
from src.core.cache import ResponseCache
from src.core.llm import LLMClient, LLMResponse


@pytest.fixture
def vocabulary():
    return [
        Entity(entity_id="grey", canonical_name="Greyfell Citadel", type="Location"),
        Entity(entity_id="iron", canonical_name="Ironfell Citadel", type="Location"),
        Entity(
            entity_id="veyra",
            canonical_name="Veyra Sunder",
            type="Character",
            aliases=["The Ashen Captain"],
        ),
        Entity(entity_id="edge", canonical_name="The Thrice-Bound Edge", type="Artifact"),
        Entity(entity_id="lantern", canonical_name="The Thrice-Bound Lantern", type="Artifact"),
        Entity(entity_id="literal", canonical_name="Shards of Will", type="Title"),
        Entity(entity_id="ember", canonical_name="Emberdeep", type="Location"),
    ]


@pytest.fixture
def analyst(vocabulary):
    return QueryAnalyst(vocabulary_loader=lambda: vocabulary)


@pytest.mark.parametrize(
    "question",
    [
        "What is Greyfell Citadel's garrison strength?",
        "How many shards of will attune The Thrice-Bound Edge?",
        "What is the power of The Thrice-Bound Lantern?",
        "What happened in Unknownland?",
        "shards of will",
        "The amber is glowing.",
    ],
)
def test_preserves_names_units_and_english(analyst, question):
    result = analyst.analyze(question)
    assert result.normalized == question
    assert result.corrections == []


@pytest.mark.parametrize("typo", ["Greyfel Citadell", "Greyflel Citadel"])
def test_safe_typo_correction_and_rollback(analyst, typo):
    question = f"What is {typo}'s garrison strength?"
    result = analyst.analyze(question)
    assert result.normalized == "What is Greyfell Citadel's garrison strength?"
    (correction,) = result.corrections
    assert correction.original == typo
    assert correction.to == "Greyfell Citadel"
    assert question[correction.start : correction.end] == typo
    assert correction.model_dump(by_alias=True)["from"] == typo
    assert analyst.analyze(question, normalize=False).normalized == question


def test_missing_greyfell_does_not_select_ironfell(vocabulary):
    agent = QueryAnalyst(vocabulary_loader=lambda: vocabulary[1:])
    question = "What is Greyfel Citadell's garrison?"
    result = agent.analyze(question)
    assert result.normalized == question
    assert result.warnings == ["normalization_skipped"]


def test_only_vocabulary_targets(analyst, vocabulary):
    allowed = {e.canonical_name for e in vocabulary if e.type != "Title"}
    for question in ["Greyfel Citadell", "Veyra Sundre", "Shards of Wlll", "Narniaa"]:
        result = analyst.analyze(question)
        assert all(c.to in allowed for c in result.corrections)
        assert all(s.type != "Title" for s in result.seed_entities)


def test_alias_links_without_rewriting(analyst):
    result = analyst.analyze("Who is The Ashen Captain?")
    assert result.corrections == []
    assert result.seed_entities[0].entity_id == "veyra"


def test_ambiguous_typo_abstains():
    entities = [
        Entity(entity_id=name, canonical_name=name, type="Location")
        for name in ["Greyfall Citadel", "Greyfell Citadel"]
    ]
    question = "What is Greyfoll Citadel?"
    result = QueryAnalyst(vocabulary_loader=lambda: entities).analyze(question)
    assert result.normalized == question
    assert result.warnings == ["normalization_skipped"]


@pytest.mark.parametrize(
    ("question", "intent", "count"),
    [
        ("Who is Veyra Sunder?", "direct", 1),
        ("How is Veyra Sunder connected to Greyfell Citadel?", "multi_hop", 2),
        ("Veyra Sunder and Greyfell Citadel", "multi_hop", 2),
        ("Compare Greyfell Citadel and Ironfell Citadel", "comparison", 2),
        ("What does the Concord seal look like", "visual", 1),
        ("Do sources agree on the actual year?", "contradiction", 1),
        ("Tell me about Veyra Sunder", "exploratory", 2),
    ],
)
def test_intent_and_decomposition(analyst, question, intent, count):
    result = analyst.analyze(question)
    assert result.intent == intent
    assert len(result.sub_questions) == count
    assert result.requires_visual == (intent == "visual")
    if count == 1:
        assert result.sub_questions == [result.normalized]
    Analysis.model_validate(result.model_dump())


def test_empty_and_long_input(analyst):
    assert analyst.analyze(" \n ").sub_questions == []
    question = "x" * 5000
    start = time.perf_counter()
    assert analyst.analyze(question).normalized == question
    assert time.perf_counter() - start < 1.0


def test_vocabulary_failure_still_classifies():
    loader = Mock(side_effect=httpx.ConnectError("offline"))
    result = QueryAnalyst(vocabulary_loader=loader).analyze("Show the figure plate")
    assert result.intent == "visual"
    assert result.warnings == ["normalization_skipped"]
    loader.assert_called_once()


def test_http_vocabulary_cache_and_title_filter(monkeypatch, tmp_path, vocabulary):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/v1/graph/entities"
        return httpx.Response(200, json={"entities": [e.model_dump() for e in vocabulary]})

    real_client = httpx.Client
    monkeypatch.setattr(
        "src.agents.analyst.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    cache = ResponseCache(tmp_path / "cache.sqlite")
    for _ in range(2):
        result = QueryAnalyst(cache=cache).analyze("Greyfell Citadel and Shards of Will")
        assert [s.entity_id for s in result.seed_entities] == ["grey"]
    assert len(requests) == 1


@pytest.mark.parametrize(
    "payload", ["not json", '{"intent":"invented"}', '{"intent":"multi_hop","sub_questions":[]}']
)
def test_bad_or_empty_llm_plan_falls_back(vocabulary, payload):
    llm = Mock(spec=LLMClient)
    llm.complete.return_value = LLMResponse(text=payload, model="test", provider="test")
    question = "Who is Veyra Sunder?"
    result = QueryAnalyst(vocabulary_loader=lambda: vocabulary, llm=llm).analyze(question)
    assert result.normalized == question
    assert result.sub_questions == [question]
    llm.complete.assert_called_once()
    messages = llm.complete.call_args.args[0]
    assert "Veyra Sunder" not in messages[0]["parts"][0]["text"]
    assert messages[1]["parts"][0]["text"].startswith("<evidence>")


def test_llm_cannot_rewrite_question(vocabulary):
    llm = Mock(spec=LLMClient)
    llm.complete.return_value = LLMResponse(
        text=json.dumps(
            {"intent": "direct", "normalized": "Ironfell Citadel", "sub_questions": ["fabricated"]}
        ),
        model="test",
        provider="test",
    )
    result = QueryAnalyst(vocabulary_loader=lambda: vocabulary, llm=llm).analyze("Greyfell Citadel")
    assert result.normalized == "Greyfell Citadel"
    assert result.sub_questions == ["Greyfell Citadel"]


def test_all_twenty_sample_questions(analyst):
    path = Path(
        os.environ.get(
            "ASHEN_SAMPLE_QUESTIONS",
            str(
                Path(__file__).resolve().parents[2]
                / "data/corpus/Ashen_Era_Archive/sample_questions.json"
            ),
        )
    )
    if not path.exists():
        pytest.skip("Corpus is not shipped in this checkout; real 20-question acceptance pending")
    payload = json.loads(path.read_text())
    questions = payload if isinstance(payload, list) else payload["questions"]
    assert len(questions) == 20
    for item in questions:
        result = analyst.analyze(item["question"])
        Analysis.model_validate(result.model_dump())
        assert result.sub_questions
        assert result.normalized == item["question"]
