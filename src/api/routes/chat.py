"""Chat service entry point: uvicorn src.api.routes.chat:create_app --factory --port 8001.

P1's app remains untouched on port 8000. Every knowledge operation crosses HTTP.
The same router can later be included in P1's app once its owner wires it there.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse

from src.agents.analyst import QueryAnalyst
from src.agents.composer import AnswerComposer
from src.agents.critic import SufficiencyCritic
from src.agents.orchestrator import Orchestrator
from src.agents.retriever import RetrievalAgent
from src.agents.runtime import BoundedLLM, Budget, KnowledgeClient
from src.agents.verifier import AnswerVerifier
from src.api.schemas import AnswerPacket, ChatRequest, Conflict, Entity, SearchHit
from src.core.cache import ResponseCache
from src.core.config import get_settings
from src.core.llm import LLMClient
from src.core.trace import TraceStore

router = APIRouter(tags=["04 Reasoning"])
_SLOTS = threading.BoundedSemaphore(4)


def get_traces() -> TraceStore:
    return TraceStore()


def get_knowledge() -> KnowledgeClient:
    settings = get_settings()
    return KnowledgeClient(
        os.environ.get("KNOWLEDGE_API_URL", "http://127.0.0.1:8000"),
        ResponseCache(settings.cache_db),
        Budget(max_wall_ms=settings.max_wall_ms),
    )


ConflictDetector = Callable[[list[SearchHit]], list[Conflict]]


def get_conflict_detector() -> ConflictDetector | None:
    """P1 supplies the implementation; absence is a visible partial result."""
    return None


def build_orchestrator(
    traces: Annotated[TraceStore, Depends(get_traces)],
    detector: Annotated[ConflictDetector | None, Depends(get_conflict_detector)],
) -> Orchestrator:
    settings = get_settings()
    budget = Budget(settings.max_steps, settings.max_tokens_per_query, settings.max_wall_ms)
    cache = ResponseCache(settings.cache_db)
    knowledge = KnowledgeClient(
        os.environ.get("KNOWLEDGE_API_URL", "http://127.0.0.1:8000"), cache, budget
    )

    def vocabulary() -> list[Entity]:
        payload = knowledge.request("GET", "/v1/graph/entities")
        return [
            Entity.model_validate(e)
            for e in (payload if isinstance(payload, list) else payload["entities"])
        ]

    llm = BoundedLLM(LLMClient(cache=cache), budget)
    return Orchestrator(
        QueryAnalyst(vocabulary_loader=vocabulary, llm=llm),
        RetrievalAgent(knowledge),
        SufficiencyCritic(llm),
        AnswerComposer(llm),
        AnswerVerifier(llm),
        traces,
        budget,
        llm=llm,
        conflict_detector=detector,
    )


def _validate(request: ChatRequest) -> None:
    if len(request.question) > 5000:
        raise HTTPException(422, "Questions must contain at most 5,000 characters")
    if request.conversation_id:
        raise HTTPException(
            422, "Conversation memory is not enabled; submit a self-contained question"
        )


@router.post("/v1/chat", response_model=AnswerPacket)
def chat(
    request: ChatRequest,
    response: Response,
    engine: Annotated[Orchestrator, Depends(build_orchestrator)],
    x_normalize: Annotated[bool, Header()] = True,
) -> AnswerPacket:
    _validate(request)
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(503, "All reasoning slots are busy; retry shortly")
    try:
        packet = engine.run(request, normalize=x_normalize)
        response.headers["X-Trace-ID"] = packet.trace_id
        return packet
    finally:
        _SLOTS.release()


@router.post("/v1/chat/jobs", status_code=202)
def start_chat(
    request: ChatRequest,
    tasks: BackgroundTasks,
    engine: Annotated[Orchestrator, Depends(build_orchestrator)],
    x_normalize: Annotated[bool, Header()] = True,
) -> dict[str, str]:
    _validate(request)
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(503, "All reasoning slots are busy; retry shortly")
    try:
        trace_id = engine.traces.start(request.question, request.mode)
    except Exception:
        _SLOTS.release()
        raise

    def run() -> None:
        try:
            engine.run(request, trace_id=trace_id, normalize=x_normalize)
        finally:
            _SLOTS.release()

    tasks.add_task(run)
    return {"trace_id": trace_id, "status": "running"}


@router.get("/v1/traces/{trace_id}")
def trace(trace_id: str, traces: Annotated[TraceStore, Depends(get_traces)]) -> dict:
    result = traces.get(trace_id)
    if result is None:
        raise HTTPException(404, "Trace not found")
    return {**result, **traces.result(trace_id)}


@router.get("/v1/assets/{asset_id}", include_in_schema=False)
def asset(asset_id: str, knowledge: Annotated[KnowledgeClient, Depends(get_knowledge)]) -> Response:
    # Only opaque IDs: no path traversal or upstream URL supplied by the caller.
    if not asset_id.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(404, "Invalid asset ID")
    try:
        content = knowledge.request("GET", f"/v1/assets/{asset_id}", binary=True)
    except Exception:
        raise HTTPException(502, "The figure could not be loaded from the knowledge API") from None
    return Response(content, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parents[3] / "ui/index.html")


def create_app(*, conflict_detector: ConflictDetector | None = None) -> FastAPI:
    app = FastAPI(title="Ashen Era — Reasoning", version="0.1.0")
    app.include_router(router)
    if conflict_detector is not None:
        app.dependency_overrides[get_conflict_detector] = lambda: conflict_detector
    return app
