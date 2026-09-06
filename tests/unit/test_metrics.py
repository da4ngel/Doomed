"""Tests for the evaluation metrics.

Written against `docs/evaluation.md`, not against the retriever. Several of these use
worked examples straight from that document, so the definition and the implementation
can be checked against each other by reading.
"""

from __future__ import annotations

import pytest

from eval.metrics import (
    QuestionResult,
    SuiteResult,
    answer_matches,
    asset_precision,
    asset_recall,
    citation_precision,
    coverage_at_k,
    first_relevant_rank,
    gain_per_step,
    groundedness,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    redundancy_rate,
)

# --------------------------------------------------------------------------
# recall / precision / coverage
# --------------------------------------------------------------------------


def test_recall_counts_gold_found() -> None:
    assert recall_at_k(["a", "b", "c"], ["a", "c"], k=10) == 1.0
    assert recall_at_k(["a", "x"], ["a", "c"], k=10) == 0.5
    assert recall_at_k(["x", "y"], ["a"], k=10) == 0.0


def test_duplicate_chunks_from_one_document_count_once() -> None:
    """Two chunks from a 250-page novel are one document found, not two."""
    assert recall_at_k(["a", "a", "a"], ["a", "b"], k=10) == 0.5


def test_k_truncates_before_scoring() -> None:
    assert recall_at_k(["x", "x2", "a"], ["a"], k=2) == 0.0
    assert recall_at_k(["x", "x2", "a"], ["a"], k=3) == 1.0


def test_coverage_is_all_or_nothing() -> None:
    """The 1B metric: a 3-document question with 2 found is a wrong answer, not 67%."""
    assert coverage_at_k(["a", "b", "c"], ["a", "b", "c"], k=10) is True
    assert coverage_at_k(["a", "b"], ["a", "b", "c"], k=10) is False


def test_coverage_and_recall_disagree_where_it_matters() -> None:
    """The reason coverage@k exists at all."""
    retrieved, gold = ["a", "b", "x"], ["a", "b", "c"]
    assert recall_at_k(retrieved, gold, k=10) == pytest.approx(2 / 3)
    assert coverage_at_k(retrieved, gold, k=10) is False


def test_precision_divides_by_k_not_by_hits() -> None:
    assert precision_at_k(["a", "x", "y", "z"], ["a"], k=4) == 0.25


def test_empty_gold_scores_zero_rather_than_raising() -> None:
    assert recall_at_k(["a"], [], k=10) == 0.0
    assert coverage_at_k(["a"], [], k=10) is False


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------


def test_ndcg_rewards_gold_placed_higher() -> None:
    high = ndcg_at_k(["a", "x", "y"], ["a"], k=10)
    low = ndcg_at_k(["x", "y", "a"], ["a"], k=10)
    assert high == 1.0
    assert low < high


def test_ndcg_of_a_perfect_multi_gold_ranking_is_one() -> None:
    assert ndcg_at_k(["a", "b", "x"], ["a", "b"], k=10) == pytest.approx(1.0)


def test_first_relevant_rank_is_one_based() -> None:
    assert first_relevant_rank(["x", "a"], ["a"], k=10) == 2
    assert first_relevant_rank(["x", "y"], ["a"], k=10) is None


def test_reciprocal_rank_matches_the_rank() -> None:
    assert reciprocal_rank(["x", "a"], ["a"], k=10) == 0.5
    assert reciprocal_rank(["x"], ["a"], k=10) == 0.0


# --------------------------------------------------------------------------
# answer-side
# --------------------------------------------------------------------------


def test_groundedness_excludes_only_inferred() -> None:
    claims = [
        {"support": "corroborated"},
        {"support": "single_source"},
        {"support": "disputed"},
        {"support": "inferred"},
    ]
    assert groundedness(claims) == 0.75


def test_groundedness_of_a_refusal_is_zero_not_an_error() -> None:
    """Refusing is a behaviour we want; it must not crash the harness."""
    assert groundedness([]) == 0.0


def test_citation_precision_punishes_a_real_citation_on_a_wrong_claim() -> None:
    assert citation_precision(["gold_doc", "unrelated"], ["gold_doc"]) == 0.5


def test_answer_matching_ignores_formatting_not_meaning() -> None:
    assert answer_matches("the garrison is 1,114 souls", ["1114"])
    assert answer_matches("The Thrice Bound Edge", ["thrice-bound edge"])
    assert not answer_matches("the garrison is 6,000 souls", ["1114"])


# --------------------------------------------------------------------------
# multimodal
# --------------------------------------------------------------------------


def test_asset_precision_punishes_dumping_every_image() -> None:
    """Attaching everything retrieved scores well on recall and destroys precision."""
    returned = ["img_gold", "img_a", "img_b", "img_c"]
    assert asset_recall(returned, ["img_gold"]) == 1.0
    assert asset_precision(returned, ["img_gold"]) == 0.25


def test_duplicate_assets_do_not_inflate_recall() -> None:
    """Asset ids are content hashes, so the two copies of a plate are one asset."""
    assert asset_recall(["img_x", "img_x"], ["img_x"]) == 1.0
    assert asset_precision(["img_x", "img_x"], ["img_x"]) == 1.0


# --------------------------------------------------------------------------
# agentic
# --------------------------------------------------------------------------


def test_gain_per_step_counts_first_sightings_only() -> None:
    """A loop re-retrieving the same document every step is not learning."""
    steps = [
        {"documents": ["a", "x"]},
        {"documents": ["a", "b"]},
        {"documents": ["a", "b"]},
    ]
    assert gain_per_step(steps, ["a", "b", "c"]) == [1, 1, 0]


def test_gain_per_step_distinguishes_churn_from_reasoning() -> None:
    churn = gain_per_step([{"documents": ["a"]}] * 3, ["a", "b"])
    reasoning = gain_per_step(
        [{"documents": ["a"]}, {"documents": ["b"]}, {"documents": ["c"]}], ["a", "b", "c"]
    )
    assert churn == [1, 0, 0]
    assert reasoning == [1, 1, 1]


def test_redundancy_rate_catches_a_rephrasing_loop() -> None:
    assert redundancy_rate(["garrison of greyfell", "Garrison  of Greyfell"]) == 0.5
    assert redundancy_rate(["a", "b", "c"]) == 0.0


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------


def _result(qid: str, covered: bool, recall: float, gold=("g",)) -> QuestionResult:
    return QuestionResult(
        qid=qid, gold_docs=list(gold), covered=covered, recall=recall, latency_ms=100
    )


def test_suite_summary_averages_only_scorable_questions() -> None:
    """A question with no gold documents cannot score retrieval. Averaging it in as 0.0
    would understate the system rather than skip it."""
    suite = SuiteResult(suite="s", config="hybrid", k=10)
    suite.results = [
        _result("q1", True, 1.0),
        _result("q2", False, 0.5),
        QuestionResult(qid="q3", gold_docs=[]),  # unscorable
    ]
    summary = suite.summary()
    assert summary["scored"] == 2
    assert summary["questions"] == 3
    assert summary["recall@10"] == 0.75
    assert summary["coverage@10"] == 0.5


def test_failures_lists_uncovered_questions_for_inspection() -> None:
    suite = SuiteResult(suite="s", config="hybrid", k=10)
    suite.results = [_result("q1", True, 1.0), _result("q2", False, 0.0)]
    assert [r.qid for r in suite.failures()] == ["q2"]


def test_empty_suite_does_not_divide_by_zero() -> None:
    assert SuiteResult(suite="s", config="c", k=10).summary()["recall@10"] == 0.0
