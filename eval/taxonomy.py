"""Label every eval miss by where the fix lives.

WHY this matters more than the failure count: most teams conflate `retrieval` and
`synthesis` and then optimise the wrong layer for a day. Reporting the split turns a list
of failures into a diagnosis - a drop in synthesis failures with flat retrieval failures
means the prompt improved; the reverse means the index did.

WHY the labels are mechanical rather than judged: the distinction is decidable from data
we already have. If the gold chunk is absent from the retrieved context it is
`retrieval`; if it is present and the answer is still wrong it is `synthesis`. Nothing
here requires an opinion, which is what makes the distribution trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Failure(StrEnum):
    """Where the fix lives. Ordered by how early in the pipeline the fault occurs."""

    EXTRACTION = "extraction"
    RETRIEVAL = "retrieval"
    SYNTHESIS = "synthesis"
    REFUSAL = "refusal"
    NONE = "none"

    @property
    def fix_lives_in(self) -> str:
        return {
            Failure.EXTRACTION: "ingestion / OCR / VLM",
            Failure.RETRIEVAL: "index / fusion / rerank",
            Failure.SYNTHESIS: "prompt / composer",
            Failure.REFUSAL: "sufficiency critic / verifier",
            Failure.NONE: "-",
        }[self]


@dataclass
class Outcome:
    """Everything needed to label one question, gathered during the run."""

    qid: str
    gold_docs: list[str]
    retrieved_docs: list[str]
    answer: str = ""
    correct: bool = False
    refused: bool = False
    answerable: bool = True
    #: True when the fact is absent from the index entirely - checked against the corpus
    #: rather than assumed, because it is the difference between a broken pipeline and a
    #: weak retriever.
    fact_in_index: bool = True


def classify(outcome: Outcome) -> Failure:
    """Label one outcome. The order of these checks IS the diagnosis.

    Extraction is tested first: if the fact never left the document, no amount of
    retrieval or prompting can recover it, and blaming the retriever would send a day of
    work at the wrong layer.
    """
    if not outcome.answerable:
        # An unanswerable question is only a failure if the system answered it anyway.
        return Failure.NONE if outcome.refused else Failure.REFUSAL

    if outcome.refused:
        # Refused something it could have answered.
        return Failure.REFUSAL

    if outcome.correct:
        return Failure.NONE

    if not outcome.fact_in_index:
        return Failure.EXTRACTION

    retrieved = set(outcome.retrieved_docs)
    if not set(outcome.gold_docs) <= retrieved:
        # The composer never saw the evidence, so the answer could not have been right.
        return Failure.RETRIEVAL

    # Gold was in context and the answer is still wrong.
    return Failure.SYNTHESIS


def distribution(outcomes: list[Outcome]) -> dict[str, int]:
    counts = dict.fromkeys((f.value for f in Failure), 0)
    for outcome in outcomes:
        counts[classify(outcome).value] += 1
    return counts


def report(outcomes: list[Outcome]) -> str:
    """Human-readable split, for the report page and the /eval command."""
    counts = distribution(outcomes)
    total = len(outcomes) or 1
    failures = total - counts[Failure.NONE.value]

    lines = [
        f"{failures} failures across {total} questions",
        "",
        f"  {'label':12s} {'n':>3s}  {'%':>5s}  fix lives in",
        f"  {'-' * 12} {'-' * 3}  {'-' * 5}  {'-' * 28}",
    ]
    for failure in Failure:
        if failure is Failure.NONE:
            continue
        count = counts[failure.value]
        lines.append(
            f"  {failure.value:12s} {count:3d}  {count / total:5.1%}  {failure.fix_lives_in}"
        )
    lines += ["", f"  {'correct':12s} {counts[Failure.NONE.value]:3d}"]

    if failures:
        worst = max(
            (f for f in Failure if f is not Failure.NONE),
            key=lambda f: counts[f.value],
        )
        lines += [
            "",
            f"Largest bucket: {worst.value} ({counts[worst.value]}). "
            f"Work on {worst.fix_lives_in} before anything else.",
        ]
    return "\n".join(lines)
