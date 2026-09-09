"""A5 proposes cited claims; IDs, metadata and accepted visuals are code-controlled."""

from __future__ import annotations

import re

from src.agents.merger import Bundle
from src.agents.runtime import CompletionClient
from src.api.schemas import AnswerMode, AnswerPacket, Claim, SearchHit, SupportLabel, Warning
from src.synthesis.citations import citation_for, find_verbatim_span
from src.synthesis.claims import Draft, ProposedClaim
from src.synthesis.extractive import numeric_figure_draft
from src.synthesis.prompts import messages
from src.synthesis.render import render_packet
from src.synthesis.visuals import bound_value, make_visual, score_asset, subject_matches

INSTRUCTION = """Compose an answer only from supplied evidence. Return JSON:
{claims: [{text, sources: [{chunk_id, quote}], asset_ids: [], confidence: 0.0}],
missing_information: []}. Every claim requires exact source quotes that entail it.
Copy quotes only from evidence_bundle text, never from candidate asset metadata.
Do not emit bibliography metadata, invented IDs or free-standing answer prose.
For a table, put the verbatim Markdown table in one claim's text and source quote.
For figures, name the exact subject in the claim. Select only assets that support that
claim. Read values as LABEL -> VALUE pairs; reference bars, axes, tolerance standards
are not the named subject. Report only the requested subject value in a numeric claim;
omit unrequested axis endpoints and tolerance values. Edge and Lantern are different;
Greyfell and Ironfell are
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
            extractive = (
                numeric_figure_draft(question, bundle.chunks, assets) if requires_visual else None
            )
            draft = extractive or self._propose(question, bundle, assets, missing)
        except Exception as error:
            packet.warnings.append(
                Warning(
                    type="tool_failure", action="composition_failed", detail=type(error).__name__
                )
            )
            return self._refuse(packet, question, "Composition could not be verified")
        placement = self._accept_draft(packet, draft, bundle, assets, question, requires_visual)
        outstanding = list(dict.fromkeys(missing + draft.missing_information))
        if packet.claims:
            # A3 lists the question itself as unresolved while it is still investigating.
            # If A5 then answers it, echoing it back marks a correct, verified answer
            # "Still unresolved" and flips the packet to partial for no reason - it did
            # that to 1a_001, 1a_004 and 1b_006, all of which were right.
            #
            # Deliberately narrow: only an entry that IS the question is dropped. A
            # genuinely unanswered part of a multi-part question is phrased differently
            # ("What are the powers of The Silent Psalter?") and must survive, because
            # that is the whole point of missing_information.
            asked = _normalise_question(question)
            outstanding = [m for m in outstanding if _normalise_question(m) != asked]
        packet.missing_information = outstanding
        if packet.claims and not outstanding:
            # Dropping the echoed question can empty missing_information while `partial`
            # is still set from the incoming A3 verdict, which leaves a packet that says
            # the answer is incomplete without saying in what way. The acceptance runner
            # calls that `partial_without_missing_information`, and it is right to: an
            # answered question with nothing outstanding is not a partial answer.
            packet.partial = False
        else:
            packet.partial = packet.partial or bool(outstanding)
        if not packet.claims:
            return self._refuse(packet, question, "No proposed claim had valid supporting evidence")
        if re.search(r"\byear\b", question, re.I) and not any(
            re.search(r"\d", claim.text) for claim in packet.claims
        ):
            packet.partial = True
            packet.missing_information.append("The requested year has not been established.")
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
                recovered = _sole_supporting_asset(proposed, sources, assets)
                if recovered is None:
                    packet.warnings.append(
                        Warning(
                            type="claim_downgraded",
                            action="removed",
                            detail="Visual question requires a supporting figure",
                        )
                    )
                    continue
                proposed = proposed.model_copy(update={"asset_ids": [recovered]})
                packet.warnings.append(
                    Warning(
                        type="claim_downgraded",
                        action="asset_rebound",
                        detail=f"Claim omitted its figure; bound the sole candidate {recovered}",
                    )
                )
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
        absent = [s.chunk_id for s in proposed.sources if s.chunk_id not in sources]
        if absent:
            packet.warnings.append(
                Warning(
                    type="claim_downgraded",
                    action="removed",
                    detail=f"Proposed claim cites chunks not in evidence: {absent}",
                )
            )
            return

        # Resolve each quote to the REAL span in its chunk. A quote that differs only by
        # whitespace or by a curly apostrophe is recovered and replaced with the verbatim
        # text; one that does not actually occur still fails. See find_verbatim_span.
        #
        # The two failures were previously one warning with no detail, so a fabricated
        # quote and a stray line break were indistinguishable in a trace.
        unmatched: list[str] = []
        for ref in proposed.sources:
            span = find_verbatim_span(ref.quote, sources[ref.chunk_id].text)
            if span is None:
                unmatched.append(ref.quote)
            else:
                ref.quote = span
        if unmatched:
            packet.warnings.append(
                Warning(
                    type="claim_downgraded",
                    action="removed",
                    detail=f"Quote not found in its cited chunk: {unmatched[0][:120]!r}",
                )
            )
            return
        proposed = _portrait_quotes(proposed, sources, assets)
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


def _normalise_question(text: str) -> str:
    """Compare questions by their words, so punctuation and spacing do not defeat it."""
    return " ".join(re.sub(r"[^\w\s]", " ", text).casefold().split())


def _sole_supporting_asset(
    proposed: ProposedClaim, sources: dict[str, SearchHit], assets: list[dict]
) -> str | None:
    """The one candidate asset carried by this claim's own cited chunks, if exactly one.

    WHY: a visual claim with no asset_ids used to be deleted outright, taking a correct
    answer with it. The model reliably finds the right evidence and unreliably remembers
    to echo the asset id back - it bound the figure on 1a_v06 and 1a_v21 and forgot on
    1a_v07 and 1a_v11, same prompt, same run.

    This does not invent a binding. It only supplies an id the cited chunk already
    carries, and only when the choice is unambiguous - one candidate asset across all
    cited chunks. Everything downstream is unchanged: `_visuals` still requires the
    subject to match and the value to be bound, so a wrong figure is still rejected. The
    guard stops discarding the answer when the evidence was right there.
    """
    candidates = {a["asset_id"] for a in assets}
    found = {
        asset_id
        for ref in proposed.sources
        if ref.chunk_id in sources
        for asset_id in sources[ref.chunk_id].asset_ids
        if asset_id in candidates
    }
    return found.pop() if len(found) == 1 else None


def _is_table(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*\|?\s*:?-{3,}.*\|", text))


def _portrait_quotes(
    proposed: ProposedClaim, sources: dict[str, SearchHit], assets: list[dict]
) -> ProposedClaim:
    """Include the indexed portrait caption when its description omits the subject name."""
    result = proposed.model_copy(deep=True)
    for ref in result.sources:
        source = sources[ref.chunk_id]
        for asset in assets:
            if (
                asset["asset_id"] not in result.asset_ids
                or asset["asset_id"] not in source.asset_ids
                or asset.get("values")
            ):
                continue
            if not subject_matches(asset, ref.quote):
                end = source.text.index(ref.quote) + len(ref.quote)
                expanded = source.text[:end]
                if subject_matches(asset, expanded):
                    ref.quote = expanded
    return result
