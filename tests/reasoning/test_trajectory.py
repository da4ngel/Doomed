from tests.reasoning.trajectory import score_trajectory


def observation(step, docs, edges=()):
    return {
        "step": step,
        "chunks": [{"chunk_id": f"c{i}", "doc_id": doc} for i, doc in enumerate(docs)],
        "edges": [{"evidence_chunk_id": edge} for edge in edges],
    }


def test_gain_counts_new_gold_documents_not_chunks_or_citations():
    trace = {
        "retrieval_evidence": [
            observation(2, ["a", "a", "decoy"]),
            observation(4, ["a", "b"]),
            observation(6, ["a", "b"]),
        ]
    }
    result = score_trajectory(trace, {"gold_docs": ["a", "b"]})
    assert [s["gold_gain"] for s in result["retrieval_steps"]] == [1, 1, 0]
    assert result["gold_document_recall"] == 1
    assert result["gold_document_coverage"] is True


def test_graph_reference_does_not_fabricate_a_retrieved_document():
    result = score_trajectory(
        {"retrieval_evidence": [observation(2, [], ["a:chunk"])]}, {"gold_docs": ["a"]}
    )
    assert result["gold_document_recall"] == 0
    assert result["retrieval_steps"][0]["graph_evidence_chunk_ids"] == ["a:chunk"]


def test_missing_telemetry_and_missing_gold_are_not_zero_scores():
    assert score_trajectory({}, {}) == {"retrieval_metrics_available": False}
    result = score_trajectory({"retrieval_evidence": [observation(2, ["a"])]}, {})
    assert result["gold_document_recall"] is None
    assert result["retrieval_steps"][0]["gold_gain"] is None
