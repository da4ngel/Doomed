"""Render an unambiguous structured figure value without another generative call."""

import re

from src.api.schemas import SearchHit
from src.synthesis.claims import Draft, ProposedClaim, SourceQuote
from src.synthesis.visuals import subject_matches


def numeric_figure_draft(
    question: str, chunks: list[SearchHit], assets: list[dict]
) -> Draft | None:
    """Only exact subject-labeled lines qualify; axis/reference values never qualify."""
    attribute = next((a for a in ["garrison", "attun", "threat"] if a in question.casefold()), None)
    if attribute is None:
        return None
    candidates = []
    for asset in assets:
        if not subject_matches(asset, question):
            continue
        for row in asset.get("values", []):
            label, value = str(row.get("label", "")), str(row.get("value", ""))
            if not subject_matches(asset, label) or not re.search(r"\d", value):
                continue
            for chunk in chunks:
                if (
                    asset["asset_id"] not in chunk.asset_ids
                    or attribute not in chunk.text.casefold()
                ):
                    continue
                # Match the source serialization, not a reconstructed model quote.
                quote = next(
                    (
                        line.strip()
                        for line in chunk.text.splitlines()
                        if line.strip() == f"{label}: {value}"
                    ),
                    None,
                )
                if quote:
                    candidates.append(
                        ProposedClaim(
                            text=quote,
                            sources=[SourceQuote(chunk_id=chunk.chunk_id, quote=quote)],
                            asset_ids=[asset["asset_id"]],
                            confidence=0.9,
                        )
                    )
    # Competing figures or values require composition/conflict handling, not a guess.
    if len(candidates) != 1:
        return None
    return Draft(claims=candidates)
