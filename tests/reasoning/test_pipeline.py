import json

import httpx
from fastapi.testclient import TestClient

from src.agents.analyst import Analysis, QueryAnalyst
from src.agents.composer import AnswerComposer
from src.agents.critic import Critique, SufficiencyCritic
from src.agents.orchestrator import Orchestrator
from src.agents.retriever import Action, RetrievalAgent
from src.agents.runtime import Budget
from src.agents.verifier import AnswerVerifier
from src.api.routes.chat import build_orchestrator, create_app, get_traces
from src.api.schemas import AnswerPacket, ChatRequest, Entity
from src.core.trace import TraceStore
from tests.reasoning.conftest import ScriptedLLM


def engine(tmp_path, knowledge, chunk, asset, *, detector=lambda chunks: []):
    question = "According to the figure plate, what is Greyfell Citadel’s garrison?"

    def handler(request):
        if request.url.path.endswith("/meta"):
            return httpx.Response(200, json=asset)
        return httpx.Response(200, json={"hits": [chunk.model_dump()]})

    llm = ScriptedLLM(
        {
            "sufficient": True,
            "covered": [
                {"sub_question": question, "chunk_id": chunk.chunk_id, "quote": chunk.text}
            ],
        },
        {
            "claims": [
                {
                    "text": chunk.text,
                    "sources": [{"chunk_id": chunk.chunk_id, "quote": chunk.text}],
                    "asset_ids": [asset["asset_id"]],
                }
            ]
        },
    )
    budget = Budget()
    agent = Orchestrator(
        QueryAnalyst(
            vocabulary_loader=lambda: [
                Entity(
                    entity_id="ent_greyfell_citadel",
                    canonical_name="Greyfell Citadel",
                    type="Location",
                )
            ]
        ),
        RetrievalAgent(knowledge(handler, budget)),
        SufficiencyCritic(llm),
        AnswerComposer(llm),
        AnswerVerifier(llm),
        TraceStore(tmp_path / "traces.sqlite"),
        budget,
        llm=llm,
        conflict_detector=detector,
    )
    return agent, question


def test_full_figure_packet_and_durable_trace(tmp_path, knowledge, chunk, asset):
    agent, question = engine(tmp_path, knowledge, chunk, asset)
    packet = agent.run(ChatRequest(question=question))
    AnswerPacket.model_validate_json(packet.model_dump_json())
    assert packet.mode == "rich" and packet.iterations == 1
    assert packet.claims and packet.visuals and not packet.partial
    assert packet.groundedness() == 1
    assert [s.agent for s in packet.reasoning_trace] == ["A1", "A2", "A3", "A4", "A5", "A6"]
    assert len(packet.usage) == 2
    reopened = TraceStore(tmp_path / "traces.sqlite")
    assert reopened.result(packet.trace_id)["packet"]["answer_markdown"] == packet.answer_markdown
    assert reopened.result(packet.trace_id)["verification"]["claims_checked"] == 1
    evidence = reopened.get(packet.trace_id)["retrieval_evidence"]
    assert len(evidence) == 1 and evidence[0]["step"] == 2
    assert evidence[0]["chunks"] == [{"chunk_id": chunk.chunk_id, "doc_id": chunk.doc_id}]
    assert evidence[0]["action"]["action"] == "figure_search"


def test_missing_p1_detector_remains_visible(tmp_path, knowledge, chunk, asset):
    agent, question = engine(tmp_path, knowledge, chunk, asset, detector=None)
    packet = agent.run(ChatRequest(question=question))
    assert packet.partial and packet.confidence <= 0.6
    assert any(w.action == "conflict_detection_unavailable" for w in packet.warnings)


class SearchingCritic:
    def assess(self, analysis, chunks, latest, step, history):
        return Critique(
            missing=["The fourth signatory house is not named."],
            next_action=Action(query=f"Unanswered signatory {step}"),
        )


def test_two_empty_steps_stop_without_churn(tmp_path, knowledge, chunk, asset):
    agent, _ = engine(tmp_path, knowledge, chunk, asset)
    agent.retriever = RetrievalAgent(knowledge(lambda r: httpx.Response(200, json={"hits": []})))
    agent.critic = SearchingCritic()
    packet = agent.run(ChatRequest(question="Name the fourth signatory house", budget=6))
    assert packet.iterations == 2
    assert packet.partial and packet.missing_information
    assert not packet.claims


def test_step_budget_is_hard_and_returns_missing(tmp_path, knowledge, chunk, asset):
    agent, question = engine(tmp_path, knowledge, chunk, asset)
    agent.critic = SearchingCritic()
    packet = agent.run(ChatRequest(question=question, budget=1))
    assert packet.iterations == 1 and packet.partial
    assert packet.missing_information
    assert any(w.type == "budget_exhausted" for w in packet.warnings)


def test_chat_and_job_routes(tmp_path, knowledge, chunk, asset):
    app = create_app()
    app.dependency_overrides[build_orchestrator] = lambda: engine(
        tmp_path, knowledge, chunk, asset
    )[0]
    app.dependency_overrides[get_traces] = lambda: TraceStore(tmp_path / "traces.sqlite")
    client = TestClient(app)
    question = engine(tmp_path, knowledge, chunk, asset)[1]
    response = client.post("/v1/chat", json={"question": question})
    assert response.status_code == 200
    assert response.headers["x-trace-id"] == response.json()["trace_id"]
    response = client.post("/v1/chat/jobs", json={"question": question})
    assert response.status_code == 202
    trace = client.get("/v1/traces/" + response.json()["trace_id"]).json()
    assert trace["packet"]["claims"]
    assert trace["verification"]["claims_checked"] == 1
    assert client.get("/v1/traces/missing").status_code == 404
    assert client.post("/v1/chat", json={"question": "x" * 5001}).status_code == 422
    assert client.post("/v1/chat", json={"question": "x", "mode": "invented"}).status_code == 422
    assert (
        client.post("/v1/chat", json={"question": "x", "conversation_id": "old"}).status_code == 422
    )
    assert "Follow the evidence" in client.get("/").text


def test_three_hop_trace_searches_new_entities(tmp_path, knowledge, chunk):
    question = "Which faction rules the home of the creature?"
    sub_questions = ["Where is the creature’s home?", "Who rules the home?"]
    chunks = [
        chunk.model_copy(
            update={
                "chunk_id": f"c{i}",
                "doc_id": f"d{i}",
                "asset_ids": [],
                "source_type": "wiki",
                "text": text,
            }
        )
        for i, text in enumerate(
            [
                "The creature lives at Marrowwell Abbey.",
                "Marrowwell Abbey is ruled by The Bleeding Crown.",
                "The Bleeding Crown is a faction.",
            ]
        )
    ]
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["query"])
        return httpx.Response(200, json={"hits": [chunks[len(calls) - 1].model_dump()]})

    llm = ScriptedLLM(
        {
            "missing": ["The ruler of Marrowwell Abbey"],
            "discovered_term": "Marrowwell Abbey",
            "next_action": {"query": "Marrowwell Abbey ruler"},
        },
        {
            "missing": ["Whether The Bleeding Crown is a faction"],
            "discovered_term": "The Bleeding Crown",
            "next_action": {"query": "The Bleeding Crown faction"},
        },
        {
            "sufficient": True,
            "covered": [
                {"sub_question": sub_questions[0], "chunk_id": "c0", "quote": chunks[0].text},
                {"sub_question": sub_questions[1], "chunk_id": "c1", "quote": chunks[1].text},
            ],
        },
        {
            "claims": [
                {"text": c.text, "sources": [{"chunk_id": c.chunk_id, "quote": c.text}]}
                for c in chunks
            ]
        },
    )

    class Analyst:
        def analyze(self, question, **kwargs):
            return Analysis(normalized=question, intent="multi_hop", sub_questions=sub_questions)

    budget = Budget()
    agent = Orchestrator(
        Analyst(),
        RetrievalAgent(knowledge(handler, budget)),
        SufficiencyCritic(llm),
        AnswerComposer(llm),
        AnswerVerifier(llm),
        TraceStore(tmp_path / "trace.sqlite"),
        budget,
        llm=llm,
        conflict_detector=lambda chunks: [],
    )
    packet = agent.run(ChatRequest(question=question, mode="agent"))
    assert packet.iterations == 3 and not packet.partial
    assert calls == [question, "Marrowwell Abbey ruler", "The Bleeding Crown faction"]
    assert len(packet.claims) == 3


def test_all_available_rich_questions_route_to_visual():
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "eval/suites/rich_1a.json"
    questions = json.loads(path.read_text())["questions"]
    assert len(questions) == 11
    agent = QueryAnalyst(vocabulary_loader=lambda: [])
    for row in questions:
        result = agent.analyze(row["question"])
        assert result.normalized == row["question"]
        assert result.requires_visual, row["qid"]
