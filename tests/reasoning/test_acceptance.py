import hashlib

import httpx

from src.api.schemas import AnswerPacket, Citation, Claim
from src.core.cache import ResponseCache
from tests.reasoning.acceptance import (
    LiveHTTP,
    lexical_match,
    load_questions,
    preflight,
    score_packet,
)


def test_empty_index_is_blocked_not_scored_zero(tmp_path):
    def handler(request):
        if request.url.path == "/v1/ready":
            return httpx.Response(200, json={"status": "not_ready", "chunks": 0})
        if request.url.path == "/v1/graph/entities":
            return httpx.Response(200, json={"total": 0, "entities": []})
        return httpx.Response(200, json={"paths": {"/v1/chat/jobs": {}}})

    client = LiveHTTP(
        "http://knowledge", ResponseCache(tmp_path / "cache"), httpx.MockTransport(handler)
    )
    result = preflight(client, client)
    assert not result["ready"] and len(result["blockers"]) == 2


def test_live_status_is_never_replayed_from_cache(tmp_path):
    responses = iter([{"status": "running"}, {"status": "ok"}])
    client = LiveHTTP(
        "http://chat",
        ResponseCache(tmp_path / "cache"),
        httpx.MockTransport(lambda request: httpx.Response(200, json=next(responses))),
    )
    assert client.request("GET", "/v1/traces/t")["status"] == "running"
    assert client.request("GET", "/v1/traces/t")["status"] == "ok"


def test_fixture_cannot_claim_real_acceptance(tmp_path):
    client = LiveHTTP(
        "http://chat",
        ResponseCache(tmp_path / "cache"),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"info": {"title": "Reasoning TEST FIXTURE"}, "paths": {}}
            )
        ),
    )
    assert any("fixture" in b for b in preflight(client, client)["blockers"])


def test_gold_in_conflict_prose_does_not_make_a_wrong_claim_correct():
    quote = "The cost is 194."
    cite = Citation(
        id="c",
        chunk_id="s",
        doc_id="d",
        title="D",
        source_type="wiki",
        authority_tier=2,
        excerpt=quote,
        excerpt_sha256=hashlib.sha256(quote.encode()).hexdigest(),
    )
    packet = AnswerPacket(
        trace_id="t",
        mode="rich",
        answer_markdown="194. A conflicting plate says 94.",
        claims=[Claim(claim_id="q", text=quote, citation_ids=["c"], support="single_source")],
        citations=[cite],
    )
    result = score_packet(packet, {"qid": "test", "accept": ["94"]})
    assert result["lexical_answer_match"] is False
    assert result["manual_review_required"]
    assert lexical_match("3,695 souls", ["3695"])


def test_all_twenty_dev_questions_available_for_live_runner():
    assert len(load_questions("dev")) == 20
    assert len({row["qid"] for row in load_questions("dev")}) == 20


def test_ready_text_index_without_images_cannot_pass_full_acceptance(tmp_path):
    def handler(request):
        if request.url.path == "/v1/ready":
            return httpx.Response(
                200, json={"status": "ready", "chunks": 2000, "images_described": 0}
            )
        if request.url.path == "/v1/graph/entities":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "entities": [
                        {"entity_id": "e", "canonical_name": "Greyfell Citadel", "type": "Location"}
                    ],
                },
            )
        return httpx.Response(200, json={"paths": {"/v1/chat/jobs": {}}})

    client = LiveHTTP(
        "http://knowledge", ResponseCache(tmp_path / "cache"), httpx.MockTransport(handler)
    )
    result = preflight(client, client)
    assert result["blockers"] == [
        "Knowledge API has no image descriptions; rich acceptance is incomplete"
    ]
