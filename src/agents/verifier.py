"""A6 validates provenance, checks entailment, and rebuilds only surviving claims."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import Field

from src.agents.runtime import CompletionClient
from src.api.schemas import AnswerPacket, Frozen, SearchHit, Warning
from src.synthesis.prompts import messages
from src.synthesis.render import literal, render_packet


class Verdict(Frozen):
    claim_id: str
    status: Literal["entailed", "unsupported", "contradicted"]


class Verdicts(Frozen):
    verdicts: list[Verdict]


class Verification(Frozen):
    claims_checked: int = 0
    claims_downgraded: int = 0
    claims_removed: int = 0
    markers_stripped: int = 0
    citations_dropped: int = 0
    confidence_adjustment: float = 0
    entailment_skipped: bool = False


class Verified(Frozen):
    packet: AnswerPacket
    verification: Verification = Field(default_factory=Verification)


class AnswerVerifier:
    def __init__(self, llm: CompletionClient | None = None) -> None:
        self.llm = llm

    def verify(
        self,
        draft: AnswerPacket,
        chunks: list[SearchHit],
        assets: list[dict],
        *,
        page_bounds: dict[tuple[str, int], tuple[float, float]] | None = None,
    ) -> Verified:
        packet = draft.model_copy(deep=True)
        report = Verification(claims_checked=len(packet.claims))
        self._citations(packet, chunks, page_bounds or {}, report)
        by_id = {c.id: c for c in packet.citations}
        statuses = self._entailment(packet, report)
        kept = []
        for claim in packet.claims:
            original_count = len(claim.citation_ids)
            claim.citation_ids = [c for c in claim.citation_ids if c in by_id]
            verdict = statuses.get(claim.claim_id, "unsupported")
            if not claim.citation_ids or verdict == "contradicted":
                report.claims_removed += 1
                packet.warnings.append(
                    Warning(type="claim_downgraded", action="removed", detail=claim.claim_id)
                )
                continue
            if verdict != "entailed" or len(claim.citation_ids) != original_count:
                claim.support, claim.confidence = "inferred", min(claim.confidence, 0.3)
                report.claims_downgraded += 1
                packet.warnings.append(
                    Warning(type="claim_downgraded", action="inferred", detail=claim.claim_id)
                )
            kept.append(claim)
        packet.claims = kept
        used = {c for claim in kept for c in claim.citation_ids}
        packet.citations = [c for c in packet.citations if c.id in used]
        placement = self._visuals(packet, chunks, assets, report)
        self._finish(packet, draft.confidence, placement, report)
        return Verified(packet=packet, verification=report)

    @staticmethod
    def _citations(
        packet: AnswerPacket, chunks: list[SearchHit], bounds: dict, report: Verification
    ) -> None:
        sources = {c.chunk_id: c for c in chunks}
        kept = []
        for citation in packet.citations:
            source = sources.get(citation.chunk_id)
            if (
                source is None
                or source.doc_id != citation.doc_id
                or not citation.excerpt
                or citation.excerpt not in source.text
                or citation.excerpt_sha256 != hashlib.sha256(citation.excerpt.encode()).hexdigest()
            ):
                report.citations_dropped += 1
                packet.warnings.append(
                    Warning(type="claim_downgraded", action="citation_dropped", detail=citation.id)
                )
                continue
            citation.authority_tier, citation.title = source.authority_tier, source.title
            citation.source_type, citation.section_path = source.source_type, source.section_path
            if citation.page != source.page or (citation.page is not None and citation.page < 1):
                citation.page = source.page if source.page and source.page > 0 else None
            dimensions = bounds.get((citation.doc_id, citation.page))
            if citation.bbox and not _valid_box(citation.bbox, dimensions):
                citation.bbox = None
                packet.warnings.append(
                    Warning(
                        type="low_ocr_confidence",
                        action="bbox_dropped",
                        detail="Page dimensions unavailable or bbox out of bounds",
                    )
                )
            kept.append(citation)
        packet.citations = kept

    def _entailment(self, packet: AnswerPacket, report: Verification) -> dict[str, str]:
        cites = {c.id: c for c in packet.citations}
        statuses = {}
        pending = []
        for claim in packet.claims:
            excerpts = [cites[c].excerpt for c in claim.citation_ids if c in cites]
            if any(claim.text in excerpt for excerpt in excerpts):
                statuses[claim.claim_id] = "entailed"
            else:
                pending.append(
                    {"claim_id": claim.claim_id, "text": claim.text, "excerpts": excerpts}
                )
        if not pending:
            return statuses
        try:
            if self.llm is None:
                raise RuntimeError("No entailment provider")
            response = self.llm.complete(
                messages(
                    "Check EACH claim against ONLY its cited excerpts. "
                    "Distinguish the exact subject, "
                    "attribute, negation, date, unit and chart label. "
                    "Mere topical similarity is not "
                    'entailment. Return {"verdicts":[{"claim_id":"...", "status":'
                    '"entailed|unsupported|contradicted"}]}.',
                    {"claims": pending},
                ),
                json_mode=True,
                max_tokens=1000,
            )
            verdicts = Verdicts.model_validate(response.json_payload()).verdicts
            if {v.claim_id for v in verdicts} != {c["claim_id"] for c in pending}:
                raise ValueError("Missing or fabricated verdict ID")
            statuses.update({v.claim_id: v.status for v in verdicts})
        except Exception:
            report.entailment_skipped = True
            # Frozen WarningType has no verification_skipped member; use action.
            packet.warnings.append(
                Warning(
                    type="tool_failure",
                    action="verification_skipped",
                    detail="Entailment unavailable; non-extractive claims are inferred",
                )
            )
        return statuses

    @staticmethod
    def _visuals(
        packet: AnswerPacket, chunks: list[SearchHit], assets: list[dict], report: Verification
    ) -> dict[str, list[str]]:
        registry = {a["asset_id"] for a in assets}
        citations = packet.citations
        valid = {
            v.id: v
            for v in packet.visuals
            if v.id in registry
            and any(
                c.doc_id == v.doc_id
                and any(
                    source.chunk_id == c.chunk_id and v.id in source.asset_ids for source in chunks
                )
                for c in citations
            )
        }
        placement: dict[str, list[str]] = {}
        for match in re.finditer(r"\[FIG:([^\]]+)\]", packet.answer_markdown):
            candidates = [
                (packet.answer_markdown.rfind(literal(c.text), 0, match.start()), c)
                for c in packet.claims
            ]
            candidates = [(position, c) for position, c in candidates if position >= 0]
            if match[1] not in valid or not candidates:
                report.markers_stripped += 1
                packet.warnings.append(Warning(type="asset_unresolved", detail=match[1]))
                continue
            claim = max(candidates, key=lambda item: item[0])[1]
            placement.setdefault(claim.claim_id, []).append(match[1])
        used = {asset for group in placement.values() for asset in group}
        packet.visuals = [visual for key, visual in valid.items() if key in used]
        for visual in packet.visuals:
            visual.url = f"/v1/assets/{visual.id}"
            visual.bbox = None  # Asset meta seam has no page geometry.
        return placement

    @staticmethod
    def _finish(packet: AnswerPacket, before: float, placement: dict, report: Verification) -> None:
        incomplete = report.claims_downgraded or report.claims_removed or not packet.claims
        if incomplete:
            packet.partial = True
            packet.missing_information.append(
                "One or more requested facts could not be verified against their cited evidence."
            )
        if any(w.action == "conflict_detection_unavailable" for w in packet.warnings):
            packet.partial = True
            packet.missing_information.append("Cross-source conflict resolution is unavailable.")
        packet.confidence = (
            sum(c.confidence for c in packet.claims) / len(packet.claims) if packet.claims else 0
        )
        if report.entailment_skipped or packet.partial:
            packet.confidence = min(packet.confidence, 0.6)
        packet.missing_information = list(dict.fromkeys(packet.missing_information))
        report.confidence_adjustment = packet.confidence - before
        packet.answer_markdown = render_packet(packet, placement)


def _valid_box(box: list[float], dimensions: tuple[float, float] | None) -> bool:
    if dimensions is None:
        return False
    x0, y0, x1, y1 = box
    return 0 <= x0 < x1 <= dimensions[0] and 0 <= y0 < y1 <= dimensions[1]
