"""Render only packet claims; verifier can rebuild without leaving rejected prose behind."""

import re

from src.api.schemas import AnswerPacket


def render_packet(packet: AnswerPacket, placement: dict[str, list[str]] | None = None) -> str:
    placement = placement or {}
    parts = []
    for claim in packet.claims:
        prefix = "Inference (not verified): " if claim.support == "inferred" else ""
        citations = " ".join(f"[{c}]" for c in claim.citation_ids)
        parts.append(f"{prefix}{literal(claim.text)}\n\n{citations}")
        parts.extend(f"[FIG:{a}]" for a in placement.get(claim.claim_id, []))
    for conflict in packet.conflicts:
        parts.append(
            literal(
                f"Sources disagree about {conflict.attribute}: {conflict.claim_a} "
                f"(tier {conflict.tier_a}) versus {conflict.claim_b} "
                f"(tier {conflict.tier_b}). {conflict.rationale}"
            )
        )
    if not packet.claims:
        parts.append("I could not establish an answer from the retrieved evidence.")
    if packet.missing_information:
        parts.append(
            "Still unresolved:\n" + "\n".join(f"- {literal(m)}" for m in packet.missing_information)
        )
    if packet.claims and packet.citations and all(c.authority_tier == 5 for c in packet.citations):
        parts.append("The only cited evidence is folkloric and may be unreliable.")
    return "\n\n".join(parts)


def literal(text: str) -> str:
    """Only code-created markers are executable; quoted marker syntax remains text."""
    return re.sub(r"\[FIG:([^\]]+)\]", r"［FIG:\1］", text)
