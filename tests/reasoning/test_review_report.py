import pytest

from tests.reasoning.review_report import summarize


def report(*results, blockers=()):
    return {"results": list(results), "preflight": {"blockers": list(blockers)}}


def test_blocked_empty_run_cannot_be_complete():
    result = summarize(report(blockers=["no service"]), [])
    assert result["status"] == "incomplete"
    assert result["mean_correctness_0_3"] is None


def test_blank_reviews_are_not_zero_or_completed():
    result = summarize(
        report({"qid": "a"}, {"qid": "b"}),
        [{"qid": "a", "correctness_0_3": "3"}, {"qid": "b", "correctness_0_3": ""}],
    )
    assert result["review_fraction"] == "1/2"
    assert result["mean_correctness_0_3"] == 3
    assert result["status"] == "incomplete"


def test_failed_request_cannot_be_scored_as_success():
    result = summarize(
        report({"qid": "a", "error": "TimeoutError"}),
        [{"qid": "a", "correctness_0_3": "3"}],
    )
    assert result["reviewed"] == 0 and result["execution_errors"] == 1


@pytest.mark.parametrize("score", ["4", "-1", "2.5", "NaN"])
def test_invalid_scores_rejected(score):
    with pytest.raises(ValueError):
        summarize(report({"qid": "a"}), [{"qid": "a", "correctness_0_3": score}])


def test_duplicate_and_unknown_reviews_rejected():
    for reviews in [[{"qid": "a"}, {"qid": "a"}], [{"qid": "other"}]]:
        with pytest.raises(ValueError):
            summarize(report({"qid": "a"}), reviews)


def test_complete_review_includes_zero_scores():
    result = summarize(report({"qid": "a"}), [{"qid": "a", "correctness_0_3": "0"}])
    assert result["status"] == "review_complete"
    assert result["mean_correctness_0_3"] == 0
