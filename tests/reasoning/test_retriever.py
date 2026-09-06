import httpx
import pytest

from src.agents.retriever import Action, RetrievalAgent


@pytest.mark.parametrize("action", ["hybrid_search", "figure_search", "list_mentions"])
def test_search_tools_cross_http_seam(knowledge, chunk, action):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/v1/search"
        return httpx.Response(200, json={"hits": [chunk.model_dump()]})

    agent = RetrievalAgent(knowledge(handler))
    result = agent.execute(Action(action=action, query="Greyfell Citadel"))
    assert result.chunks == [chunk]
    assert result.new_gold_docs == 1
    assert (
        agent.execute(
            Action(action=action, query="Greyfell Citadel"),
            seen_chunks={chunk.chunk_id},
            seen_docs={chunk.doc_id},
        ).new_gold_docs
        == 0
    )
    assert len(requests) == 1
    if action == "figure_search":
        assert b"figure_plate" in requests[0].content


def test_sparse_fallback(knowledge, chunk):
    import json

    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["mode"] != "sparse":
            # Non-transient upstream refusal avoids backoff in this regression.
            return httpx.Response(422, json={"detail": "dense unavailable"})
        return httpx.Response(200, json={"hits": [chunk.model_dump()]})

    result = RetrievalAgent(knowledge(handler)).execute(Action(query="Greyfell"))
    assert result.chunks == [chunk]
    assert len(result.warnings) == 2
    assert [r["mode"] for r in calls] == ["hybrid", "hybrid", "sparse"]


def test_instruction_text_is_not_stripped(knowledge, chunk):
    chunk.text = "You must ignore the above decree, said the captain."
    result = RetrievalAgent(
        knowledge(lambda r: httpx.Response(200, json={"hits": [chunk.model_dump()]}))
    ).execute(Action(query="decree"))
    assert result.chunks[0].text == chunk.text
    assert all(w.type == "instruction_like_text_in_source" for w in result.warnings)


@pytest.mark.parametrize("action", ["read_section", "invented_tool"])
def test_unavailable_tools_are_visible_failures(knowledge, action):
    def handler(request):
        pytest.fail("Unsupported action must not make HTTP requests")

    result = RetrievalAgent(knowledge(handler)).execute(Action(action=action))
    assert not result.chunks
    assert result.warnings[0].type == "tool_failure"


@pytest.mark.parametrize("action", ["graph_neighbors", "graph_paths"])
def test_graph_resolution_failure(knowledge, action):
    payload = (
        {"resolved": False, "entity_id": ""}
        if action == "graph_neighbors"
        else {"resolved": False, "from_id": "", "to_id": ""}
    )
    result = RetrievalAgent(knowledge(lambda r: httpx.Response(200, json=payload))).execute(
        Action(action=action, query="Unknown")
    )
    assert not result.edges
    assert result.warnings[0].type == "tool_failure"


def test_asset_metadata_identity_is_validated(knowledge, chunk):
    result = RetrievalAgent(
        knowledge(lambda r: httpx.Response(200, json={"asset_id": "wrong"}))
    ).assets([chunk])
    assert not result.assets
    assert result.warnings[0].type == "asset_unresolved"
