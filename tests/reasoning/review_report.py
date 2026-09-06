"""Summarize completed human acceptance reviews without filling in missing judgments.

Usage: python -m tests.reasoning.review_report /tmp/ashen-acceptance/RUN_DIRECTORY
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def summarize(report: dict, reviews: list[dict]) -> dict:
    results = report["results"]
    expected = {row["qid"] for row in results}
    indexed: dict[str, dict] = {}
    for row in reviews:
        qid = row["qid"]
        if qid not in expected or qid in indexed:
            raise ValueError(f"Unknown or duplicate review qid: {qid}")
        score = row.get("correctness_0_3", "").strip()
        refusal = row.get("refusal_correct", "").strip().lower()
        if score not in {"", "0", "1", "2", "3"}:
            raise ValueError(f"Correctness must be blank or an integer 0–3: {qid}")
        if refusal not in {"", "true", "false"}:
            raise ValueError(f"Refusal judgment must be blank, true, or false: {qid}")
        indexed[qid] = {"score": int(score) if score else None, "refusal": refusal}
    successful = [r for r in results if "error" not in r]
    scores = [indexed[r["qid"]]["score"] for r in successful if r["qid"] in indexed]
    scores = [score for score in scores if score is not None]
    complete = bool(results) and len(scores) == len(results) and not report["preflight"]["blockers"]
    return {
        "status": "review_complete" if complete else "incomplete",
        "attempted": len(results),
        "execution_errors": len(results) - len(successful),
        "reviewed": len(scores),
        "review_fraction": f"{len(scores)}/{len(results)}",
        "mean_correctness_0_3": sum(scores) / len(scores) if scores else None,
        "mean_scope": "reviewed successful questions only",
        "structural_error_questions": sum(bool(r.get("structural_errors")) for r in successful),
        "blockers": report["preflight"]["blockers"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    directory = parser.parse_args().directory
    report = json.loads((directory / "report.json").read_text())
    with (directory / "human-review.csv").open(newline="") as handle:
        reviews = list(csv.DictReader(handle))
    summary = summarize(report, reviews)
    (directory / "review-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "review_complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
