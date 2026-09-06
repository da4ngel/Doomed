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
