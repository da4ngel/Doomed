from src.agents.analyst import Analysis
from src.agents.critic import SufficiencyCritic
from src.agents.retriever import Action, Evidence
from tests.reasoning.conftest import ScriptedLLM


def test_direct_coverage_requires_exact_quote(chunk):
    question = "What is the garrison of Greyfell Citadel?"
    llm = ScriptedLLM(
        {
            "sufficient": True,
            "covered": [
                {"sub_question": question, "chunk_id": chunk.chunk_id, "quote": chunk.text}
            ],
        }
    )
    result = SufficiencyCritic(llm).assess(
        Analysis(normalized=question, sub_questions=[question]),
        [chunk],
        Evidence(chunks=[chunk]),
        1,
        [],
    )
    assert result.sufficient


def test_multihop_uses_newly_discovered_term(chunk):
    question = "Who rules the lair of Gravemaw Wyrm?"
    chunk.text = "Gravemaw Wyrm has its lair at Marrowwell Abbey."
    llm = ScriptedLLM(
        {
            "sufficient": False,
            "missing": ["Who rules Marrowwell Abbey?"],
            "discovered_term": "Marrowwell Abbey",
            "next_action": {"action": "hybrid_search", "query": "Marrowwell Abbey ruler"},
            "reason": "The latest chunk names Marrowwell Abbey as the lair.",
        }
    )
    result = SufficiencyCritic(llm).assess(
        Analysis(normalized=question, intent="multi_hop", sub_questions=[question]),
        [chunk],
        Evidence(chunks=[chunk]),
        1,
        [Action(query=question)],
    )
    assert not result.sufficient
    assert "Marrowwell Abbey" in result.next_action.query
    assert "Marrowwell Abbey" not in question


def test_invented_next_term_is_rejected(chunk):
    question = "Where is the lair?"
    llm = ScriptedLLM(
        {
            "sufficient": False,
            "discovered_term": "Narnia",
            "next_action": {"action": "hybrid_search", "query": "Narnia ruler"},
        }
    )
    result = SufficiencyCritic(llm).assess(
        Analysis(normalized=question, intent="multi_hop", sub_questions=[question]),
        [chunk],
        Evidence(chunks=[chunk]),
        1,
        [Action(query=question)],
    )
    assert result.next_action is None
    assert result.missing


def test_malformed_critic_is_partial_after_one_repair(chunk):
    llm = ScriptedLLM({"bad": True}, {"bad": True})
    result = SufficiencyCritic(llm).assess(
        Analysis(normalized="Question", sub_questions=["Question"]),
        [chunk],
        Evidence(chunks=[chunk]),
        1,
        [],
    )
    assert result.degraded and not result.sufficient
    assert len(llm.calls) == 2


def test_a_repeated_old_entity_is_not_a_new_discovery(chunk):
    question = "Who rules the lair?"
    chunk.text = "The lair is Marrowwell Abbey."
    response = {
        "discovered_term": "Marrowwell Abbey",
        "next_action": {"query": "Marrowwell Abbey ruler"},
        "missing": ["The ruler"],
    }
    critic = SufficiencyCritic(ScriptedLLM(response, response))
    analysis = Analysis(normalized=question, intent="multi_hop", sub_questions=[question])
    first = critic.assess(analysis, [chunk], Evidence(chunks=[chunk]), 1, [Action(query=question)])
    assert first.next_action is not None
    second = critic.assess(analysis, [chunk], Evidence(chunks=[chunk]), 2, [Action(query=question)])
    assert second.next_action is None


def test_latest_evidence_references_existing_text_without_duplication(chunk):
    import json

    from tests.reasoning.conftest import ScriptedLLM

    llm = ScriptedLLM({"sufficient": False, "missing": ["unknown"]})
    SufficiencyCritic(llm).assess(
        Analysis(normalized="Question", sub_questions=["Question"]),
        [chunk],
        Evidence(chunks=[chunk]),
        1,
        [],
    )
    text = llm.calls[0][0][1]["parts"][0]["text"]
    payload = json.loads(text.removeprefix("<evidence>").removesuffix("</evidence>"))
    assert payload["latest"]["chunk_ids"] == [chunk.chunk_id]
    assert payload["evidence_so_far"][0]["text"] == chunk.text
    assert "chunks" not in payload["latest"]


def test_completed_coverage_accepts_no_discovered_term(chunk):
    llm = ScriptedLLM(
        {
            "sufficient": True,
            "covered": [
                {"sub_question": "Question", "chunk_id": chunk.chunk_id, "quote": chunk.text}
            ],
            "next_action": None,
            "discovered_term": None,
        }
    )
    result = SufficiencyCritic(llm).assess(
        Analysis(normalized="Question", sub_questions=["Question"]),
        [chunk],
        Evidence(chunks=[chunk]),
        1,
        [],
    )
    assert result.sufficient and not result.degraded
    assert len(llm.calls) == 1


def test_graph_discovery_retrieves_citable_text_before_more_graph_hops():
    from src.api.schemas import GraphEdgeOut

    edge = GraphEdgeOut(
        subject_id="beast",
        subject="Beast",
        predicate="lair_of",
        object_id="abbey",
        object="Hidden Abbey",
        evidence_chunk_id="wiki/beast.md#row",
        authority_tier=2,
    )
    llm = ScriptedLLM(
        {
            "sufficient": False,
            "missing": ["Who rules Hidden Abbey?"],
            "discovered_term": "Hidden Abbey",
            "next_action": {
                "action": "graph_neighbors",
                "query": "Hidden Abbey",
                "args": {"entity_id": "abbey"},
            },
        }
    )
    result = SufficiencyCritic(llm).assess(
        Analysis(
            normalized="Who rules the lair of Beast?",
            intent="multi_hop",
            sub_questions=["Who rules the lair of Beast?"],
        ),
        [],
        Evidence(edges=[edge]),
        1,
        [Action(action="graph_neighbors", query="Beast")],
    )
    assert result.next_action.action == "hybrid_search"
    assert result.next_action.query == "Hidden Abbey"
    assert not result.sufficient
