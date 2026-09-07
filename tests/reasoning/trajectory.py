"""Measure retrieved source documents independently of the final answer's citations."""


def score_trajectory(trace: dict, row: dict) -> dict:
    """Graph chunk references remain references until an observed hit supplies a doc ID."""
    observations = trace.get("retrieval_evidence")
    if observations is None:
        return {"retrieval_metrics_available": False}
    gold = set(row.get("gold_docs", []) + row.get("gold_assets", []))
    seen: set[str] = set()
    steps = []
    for observation in observations:
        docs = {chunk["doc_id"] for chunk in observation["chunks"]}
        new = docs - seen
        seen.update(docs)
        steps.append(
            {
                "step": observation["step"],
                "new_documents": sorted(new),
                "new_gold_documents": sorted(new & gold) if gold else None,
                "gold_gain": len(new & gold) if gold else None,
                "cumulative_gold_recall": len(seen & gold) / len(gold) if gold else None,
                "graph_evidence_chunk_ids": sorted(
                    {edge["evidence_chunk_id"] for edge in observation["edges"]}
                ),
            }
        )
    return {
        "retrieval_metrics_available": True,
        "retrieved_document_ids": sorted(seen),
        "retrieval_steps": steps,
        "gold_document_recall": len(seen & gold) / len(gold) if gold else None,
        "gold_document_coverage": gold <= seen if gold else None,
    }
