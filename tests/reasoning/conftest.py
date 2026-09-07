from __future__ import annotations

import json

import httpx
import pytest

from src.agents.runtime import Budget, KnowledgeClient
from src.api.schemas import SearchHit
from src.core.cache import ResponseCache
from src.core.llm import LLMResponse


class ScriptedLLM:
    """Test-only responses; these are not claims of model or corpus accuracy."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.usage = []

    def complete(self, messages, **params):
        self.calls.append((messages, params))
        if not self.responses:
            raise RuntimeError("No scripted response")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(messages)
        response = LLMResponse(
            text=json.dumps(value), model="fixture", provider="fixture", tokens_in=10, tokens_out=5
        )
        self.usage.append(response)
        return response


@pytest.fixture
def chunk():
    return SearchHit(
        chunk_id="plate:c1",
        doc_id="plate",
        title="Greyfell plate",
        score=0.9,
        text="Greyfell Citadel: 3,695 souls under arms.",
        page=1,
        source_type="figure_plate",
        authority_tier=1,
        asset_ids=["asset_grey"],
    )


@pytest.fixture
def asset():
    return {
        "asset_id": "asset_grey",
        "entity_link": "ent_greyfell_citadel",
        "subject": "Greyfell Citadel",
        "kind": "bar_chart",
        "caption": "Garrison strength",
        "values": [
            {"label": "Greyfell Citadel", "value": "3,695"},
            {"label": "Great Keep standard", "value": "6,000"},
        ],
        "description": "Greyfell Citadel garrison and reference standard.",
    }


@pytest.fixture
def knowledge(tmp_path):
    def factory(handler, budget=None):
        return KnowledgeClient(
            "http://knowledge",
            ResponseCache(tmp_path / "http.sqlite"),
            budget or Budget(max_wall_ms=5000),
            httpx.MockTransport(handler),
        )

    return factory
