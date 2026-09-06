"""Offline UI/Postman fixture. All responses are scripted, not a corpus evaluation."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src.agents.analyst import QueryAnalyst
from src.agents.composer import AnswerComposer
from src.agents.critic import SufficiencyCritic
from src.agents.orchestrator import Orchestrator
from src.agents.retriever import RetrievalAgent
from src.agents.runtime import Budget, KnowledgeClient
from src.agents.verifier import AnswerVerifier
from src.api.routes.chat import build_orchestrator, get_knowledge, get_traces, router
from src.api.schemas import Entity, SearchHit
from src.core.cache import ResponseCache
from src.core.trace import TraceStore
from tests.reasoning.conftest import ScriptedLLM

ROOT = Path(os.environ.get("REASONING_FIXTURE_DIR", "/tmp/doomed-reasoning-fixture"))
CHUNK = SearchHit(
    chunk_id="fixture:c1",
    doc_id="fixture",
    title="SCRIPTED TEST FIXTURE",
    score=1,
    text="Greyfell Citadel: 3,695 souls under arms.",
    page=1,
    source_type="figure_plate",
    authority_tier=1,
    asset_ids=["fixture_image"],
)
ASSET = {
    "asset_id": "fixture_image",
    "entity_link": "ent_greyfell_citadel",
    "subject": "Greyfell Citadel",
    "kind": "bar_chart",
    "caption": "TEST FIXTURE — not the corpus image",
    "values": [{"label": "Greyfell Citadel", "value": "3,695"}],
}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/meta"):
        return httpx.Response(200, json=ASSET)
    if request.url.path.startswith("/v1/assets/"):
        # One-pixel PNG intentionally cannot be mistaken for a real corpus plate.
        return httpx.Response(
            200,
            content=base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGMsAAAAASUVORK5CYII="
            ),
        )
    query = json.loads(request.content).get("query", "")
    hits = [CHUNK.model_dump()] if "Greyfell Citadel" in query else []
    return httpx.Response(200, json={"hits": hits})


def _knowledge() -> KnowledgeClient:
    return KnowledgeClient(
        "http://fixture",
        ResponseCache(ROOT / "cache.sqlite"),
        Budget(),
        httpx.MockTransport(_handler),
    )


def _engine() -> Orchestrator:
    def critic(messages: list[dict]) -> dict:
        text = messages[1]["parts"][0]["text"]
        payload = json.loads(text.removeprefix("<evidence>").removesuffix("</evidence>"))
        covered = [
            {"sub_question": q, "chunk_id": CHUNK.chunk_id, "quote": CHUNK.text}
            for q in payload["sub_questions"]
            if payload["evidence_so_far"]
        ]
        return {
            "sufficient": bool(covered),
            "covered": covered,
            "missing": [] if covered else [payload["question"]],
        }

    llm = ScriptedLLM(
        critic,
        {
            "claims": [
                {
                    "text": CHUNK.text,
                    "sources": [{"chunk_id": CHUNK.chunk_id, "quote": CHUNK.text}],
                    "asset_ids": [ASSET["asset_id"]],
                }
            ]
        },
    )
    return Orchestrator(
        QueryAnalyst(
            vocabulary_loader=lambda: [
                Entity(
                    entity_id="ent_greyfell_citadel",
                    canonical_name="Greyfell Citadel",
                    type="Location",
                )
            ]
        ),
        RetrievalAgent(_knowledge()),
        SufficiencyCritic(llm),
        AnswerComposer(llm),
        AnswerVerifier(llm),
        TraceStore(ROOT / "trace.sqlite"),
        Budget(),
        llm=llm,
        conflict_detector=lambda chunks: [],
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Reasoning TEST FIXTURE")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        html = (Path(__file__).resolve().parents[2] / "ui/index.html").read_text()
        return html.replace(
            "<body>",
            '<body><p class="notice">TEST FIXTURE — scripted responses; '
            "not a live corpus run.</p>",
        )

    app.include_router(router)
    app.dependency_overrides[build_orchestrator] = _engine
    app.dependency_overrides[get_traces] = lambda: TraceStore(ROOT / "trace.sqlite")
    app.dependency_overrides[get_knowledge] = _knowledge
    return app
