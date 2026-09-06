"""A5 proposes cited claims; IDs, metadata and accepted visuals are code-controlled."""

from __future__ import annotations

import re

from src.agents.merger import Bundle
from src.agents.runtime import CompletionClient
from src.api.schemas import AnswerMode, AnswerPacket, Claim, SearchHit, SupportLabel, Warning
from src.synthesis.citations import citation_for
from src.synthesis.claims import Draft, ProposedClaim
from src.synthesis.prompts import messages
from src.synthesis.render import render_packet
from src.synthesis.visuals import bound_value, make_visual, score_asset, subject_matches

INSTRUCTION = """Compose an answer only from supplied evidence. Return JSON:
{claims: [{text, sources: [{chunk_id, quote}], asset_ids: [], confidence: 0.0}],
missing_information: []}. Every claim requires exact source quotes that entail it.
Do not emit bibliography metadata, invented IDs or free-standing answer prose.
For a table, put the verbatim Markdown table in one claim's text and source quote.
For figures, name the exact subject in the claim. Select only assets that support that
claim. Read values as LABEL -> VALUE pairs; reference bars, axes, tolerance standards
are not the named subject. Edge and Lantern are different; Greyfell and Ironfell are
different. Never substitute a nearby entity when the requested subject is absent.
Prefer lower-numbered authority tiers on the SAME subject and attribute, even when
lower-authority text ranks first. Report conflicts; never silently blend values.
Do not map an unknown unit onto a familiar unit: report the unit actually evidenced.
If evidence supports nothing, return no claims and name what could not be established.
"""


class AnswerComposer:
    def __init__(self, llm: CompletionClient | None = None) -> None:
        self.llm = llm

    def compose(
        self,
        question: str,
        bundle: Bundle,
        assets: list[dict],
        *,
        trace_id: str,
        mode: AnswerMode,
        missing: list[str],
        partial: bool,
        requires_visual: bool = False,
    ) -> AnswerPacket:
        packet = AnswerPacket(
            trace_id=trace_id,
            mode=mode,
            conflicts=bundle.conflicts,
            warnings=list(bundle.warnings),
            partial=partial,
            missing_information=list(missing),
        )
        if not bundle.chunks or self.llm is None:
            return self._refuse(packet, question, "No verified composition is available")
        try:
            draft = self._propose(question, bundle, assets, missing)
        except Exception as error:
            packet.warnings.append(
                Warning(
                    type="tool_failure", action="composition_failed", detail=type(error).__name__
                )
            )
            return self._refuse(packet, question, "Composition could not be verified")
        placement = self._accept_draft(packet, draft, bundle, assets, question, requires_visual)
        packet.missing_information = list(dict.fromkeys(missing + draft.missing_information))
        if not packet.claims:
            return self._refuse(packet, question, "No proposed claim had valid supporting evidence")
        packet.answer_markdown = render_packet(packet, placement)
        packet.confidence = min(c.confidence for c in packet.claims)
        return packet

    def _accept_draft(
        self,
        packet: AnswerPacket,
        draft: Draft,
        bundle: Bundle,
        assets: list[dict],
        question: str,
        requires_visual: bool,
    ) -> dict[str, list[str]]:
        sources = {c.chunk_id: c for c in bundle.chunks}
        placement: dict[str, list[str]] = {}
        for proposed in draft.claims:
            if requires_visual and not proposed.asset_ids and not _is_table(proposed.text):
                packet.warnings.append(
                    Warning(
                        type="claim_downgraded",
                        action="removed",
                        detail="Visual question requires a supporting figure",
                    )
                )
                continue
            self._accept(packet, proposed, sources, assets, question, placement)
        return placement

    def _propose(
        self, question: str, bundle: Bundle, assets: list[dict], missing: list[str]
    ) -> Draft:
        assert self.llm is not None
        payload = {
            "question": question,
            "evidence_bundle": [c.model_dump() for c in bundle.chunks],
            "candidate_assets": assets,
            "conflicts": [c.model_dump() for c in bundle.conflicts],
            "missing": missing,
            "reliability_notes": bundle.reliability_notes,
        }
        response = self.llm.complete(
            messages(INSTRUCTION, payload), json_mode=True, max_tokens=2400
        )
        return Draft.model_validate(response.json_payload())

    def _accept(
        self,
        packet: AnswerPacket,
        proposed: ProposedClaim,
        sources: dict[str, SearchHit],
        assets: list[dict],
        question: str,
        placement: dict[str, list[str]],
    ) -> None:
        if any(
            s.chunk_id not in sources or s.quote not in sources[s.chunk_id].text
            for s in proposed.sources
        ):
            packet.warnings.append(
                Warning(
                    type="claim_downgraded",
                    action="removed",
                    detail="Proposed claim cites an absent chunk or fabricated quote",
                )
            )
            return
        citations = [citation_for(sources[s.chunk_id], s.quote) for s in proposed.sources]
        claim_id = f"claim_{len(packet.claims) + 1}"
        accepted = self._visuals(proposed, sources, assets, question)
        if proposed.asset_ids and not accepted:
            packet.warnings.append(
                Warning(
                    type="claim_downgraded",
                    action="removed",
                    detail="Figure claim failed exact subject/label binding",
                )
            )
            return
        for citation in citations:
            if citation.id not in {c.id for c in packet.citations}:
                packet.citations.append(citation)
        support = _support(citations)
        packet.claims.append(
            Claim(
                claim_id=claim_id,
                text=proposed.text,
                citation_ids=[c.id for c in citations],
                support=support,
                confidence=proposed.confidence,
            )
        )
        placement[claim_id] = [v.id for v in accepted]
        packet.visuals.extend(v for v in accepted if v.id not in {a.id for a in packet.visuals})

    @staticmethod
    def _visuals(
        proposed: ProposedClaim, sources: dict[str, SearchHit], assets: list[dict], question: str
    ) -> list:
        accepted = []
        for asset in assets:
            if asset["asset_id"] not in proposed.asset_ids:
                continue
            score = score_asset(asset, question, proposed.text)
            for ref in proposed.sources:
                chunk = sources[ref.chunk_id]
                if (
                    score >= 0.8
                    and asset["asset_id"] in chunk.asset_ids
                    and bound_value(asset, proposed.text, ref.quote)
                    and subject_matches(asset, ref.quote)
                ):
                    accepted.append(make_visual(asset, chunk, score))
                    break
        return accepted

    @staticmethod
    def _refuse(packet: AnswerPacket, question: str, reason: str) -> AnswerPacket:
        packet.partial = True
        packet.missing_information = list(
            dict.fromkeys(packet.missing_information + [f"{reason}: {question}"])
        )
        packet.confidence = 0
        packet.answer_markdown = render_packet(packet)
        return packet


def _support(citations: list) -> SupportLabel:
    """Duplicate excerpts do not establish independent corroboration."""
    docs = {c.doc_id for c in citations}
    texts = {" ".join(c.excerpt.split()).casefold() for c in citations}
    return "corroborated" if len(docs) > 1 and len(texts) > 1 else "single_source"


def _is_table(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*\|?\s*:?-{3,}.*\|", text))
