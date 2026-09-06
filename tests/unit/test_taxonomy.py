"""Tests for the failure taxonomy.

The labels have to be mechanical, because a distribution that depends on judgement is a
distribution nobody can trust. Each test pins one decision boundary.
"""

from __future__ import annotations

from eval.taxonomy import Failure, Outcome, classify, distribution, report


def _outcome(**kwargs) -> Outcome:
    base = {
        "qid": "q",
        "gold_docs": ["g1"],
        "retrieved_docs": ["g1"],
        "correct": True,
        "refused": False,
        "answerable": True,
        "fact_in_index": True,
    }
    return Outcome(**{**base, **kwargs})


def test_a_correct_answer_is_not_a_failure() -> None:
    assert classify(_outcome()) is Failure.NONE


def test_gold_missing_from_context_is_retrieval() -> None:
    """The composer never saw the evidence, so the answer could not have been right.
    Blaming the prompt here sends a day of work at the wrong layer."""
    outcome = _outcome(correct=False, retrieved_docs=["other"])
    assert classify(outcome) is Failure.RETRIEVAL
    assert classify(outcome).fix_lives_in == "index / fusion / rerank"


def test_gold_present_but_answer_wrong_is_synthesis() -> None:
    outcome = _outcome(correct=False, retrieved_docs=["g1", "other"])
    assert classify(outcome) is Failure.SYNTHESIS
    assert classify(outcome).fix_lives_in == "prompt / composer"


def test_fact_absent_from_the_index_is_extraction_not_retrieval() -> None:
    """Checked first on purpose: if the fact never left the document, no retriever or
    prompt can recover it."""
    outcome = _outcome(correct=False, retrieved_docs=[], fact_in_index=False)
    assert classify(outcome) is Failure.EXTRACTION


def test_refusing_an_answerable_question_is_a_refusal_failure() -> None:
    assert classify(_outcome(correct=False, refused=True)) is Failure.REFUSAL


def test_refusing_an_unanswerable_question_is_correct_behaviour() -> None:
    """The behaviour we actually want must not be scored as a failure."""
    assert classify(_outcome(answerable=False, refused=True, correct=False)) is Failure.NONE


def test_answering_an_unanswerable_question_is_a_refusal_failure() -> None:
    """The hallucination case, and the one judges will probe."""
    assert classify(_outcome(answerable=False, refused=False, correct=False)) is Failure.REFUSAL


def test_extraction_is_checked_before_retrieval() -> None:
    """Both conditions hold here; the earlier fault wins, because fixing retrieval
    would not help."""
    outcome = _outcome(correct=False, retrieved_docs=["other"], fact_in_index=False)
    assert classify(outcome) is Failure.EXTRACTION


def test_distribution_counts_every_question_once() -> None:
    outcomes = [
        _outcome(qid="a"),
        _outcome(qid="b", correct=False, retrieved_docs=["x"]),
        _outcome(qid="c", correct=False),
        _outcome(qid="d", answerable=False, refused=False, correct=False),
    ]
    counts = distribution(outcomes)
    assert sum(counts.values()) == 4
    assert counts["retrieval"] == 1
    assert counts["synthesis"] == 1
    assert counts["refusal"] == 1
    assert counts["none"] == 1


def test_report_names_the_layer_to_work_on() -> None:
    """The point of the split: it should tell you where to spend tomorrow."""
    outcomes = [_outcome(qid=str(i), correct=False, retrieved_docs=["x"]) for i in range(3)] + [
        _outcome(qid="ok")
    ]
    text = report(outcomes)
    assert "retrieval" in text
    assert "index / fusion / rerank" in text
    assert "Largest bucket: retrieval" in text


def test_report_of_a_clean_run_claims_no_largest_bucket() -> None:
    text = report([_outcome(qid="a"), _outcome(qid="b")])
    assert "Largest bucket" not in text
