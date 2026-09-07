import hashlib

import pytest

from src.agents.composer import AnswerComposer
from src.agents.merger import Bundle, merge_evidence
from src.agents.verifier import AnswerVerifier
from src.api.schemas import Conflict
from tests.reasoning.conftest import ScriptedLLM


def compose(chunk, assets=(), text=None, quote=None, visual_ids=(), requires_visual=False):
    llm = ScriptedLLM(
        {
            "claims": [
                {
                    "text": text or chunk.text,
                    "sources": [{"chunk_id": chunk.chunk_id, "quote": quote or chunk.text}],
                    "asset_ids": list(visual_ids),
                }
            ]
        }
    )
    return AnswerComposer(llm).compose(
        "What is Greyfell Citadel's garrison?",
        Bundle(chunks=[chunk]),
        list(assets),
        trace_id="test",
        mode="rich",
        missing=[],
        partial=False,
        requires_visual=requires_visual,
    )


def test_figure_has_bound_citation_and_inline_marker(chunk, asset):
    packet = compose(chunk, [asset], visual_ids=[asset["asset_id"]], requires_visual=True)
    assert packet.claims[0].citation_ids == [packet.citations[0].id]
    assert packet.citations[0].excerpt_sha256 == hashlib.sha256(chunk.text.encode()).hexdigest()
    assert packet.visuals[0].relevance >= 0.8
    assert "[FIG:asset_grey]" in packet.answer_markdown
    result = AnswerVerifier().verify(packet, [chunk], [asset])
    assert result.packet.claims[0].support == "single_source"
    assert result.verification.claims_downgraded == 0


@pytest.mark.parametrize("mutation", ["wrong_subject", "reference_bar", "no_asset"])
def test_chart_decoys_cannot_be_answers(chunk, asset, mutation):
    text, quote = chunk.text, chunk.text
    ids = [asset["asset_id"]]
    if mutation == "wrong_subject":
        asset["subject"], asset["entity_link"] = "Ironfell Citadel", "ent_ironfell_citadel"
    if mutation == "reference_bar":
        chunk.text += "\nGreat Keep standard: 6,000."
        text, quote = "Greyfell Citadel: 6,000.", "Great Keep standard: 6,000."
    if mutation == "no_asset":
        ids = []
    packet = compose(chunk, [asset], text=text, quote=quote, visual_ids=ids, requires_visual=True)
    assert not packet.claims
    assert packet.partial and packet.missing_information


def test_same_number_on_subject_and_reference_still_requires_label(chunk, asset):
    asset["values"] = [
        {"label": "Greyfell Citadel", "value": "55"},
        {"label": "Adept tolerance", "value": "55"},
    ]
    chunk.text = "Greyfell Citadel: 55.\nAdept tolerance: 55."
    packet = compose(
        chunk,
        [asset],
        text="Greyfell Citadel: 55.",
        quote="Adept tolerance: 55.",
        visual_ids=[asset["asset_id"]],
    )
    assert packet.claims == []


def test_table_survives_as_table(chunk):
    chunk.text = "| House | Year |\n| --- | --- |\n| Greyfell | 412 |"
    packet = compose(chunk)
    assert chunk.text in packet.answer_markdown


def test_empty_bundle_refuses():
    packet = AnswerComposer().compose(
        "Who owns the moon?", Bundle(), [], trace_id="test", mode="agent", missing=[], partial=False
    )
    assert not packet.claims and packet.missing_information and packet.partial


def test_fabricated_quote_rejected(chunk):
    assert not compose(chunk, quote="There are 9,999 soldiers").claims


def test_unentailed_claim_is_inferred(chunk):
    packet = compose(chunk, text="Greyfell Citadel has a dragon.")
    verified = AnswerVerifier(
        ScriptedLLM({"verdicts": [{"claim_id": "claim_1", "status": "unsupported"}]})
    ).verify(packet, [chunk], [])
    assert verified.packet.claims[0].support == "inferred"
    assert verified.packet.groundedness() == 0
    assert verified.verification.claims_downgraded == 1
    assert "Inference (not verified)" in verified.packet.answer_markdown


def test_contradicted_claim_is_removed_from_prose(chunk):
    packet = compose(chunk, text="Greyfell Citadel has no garrison.")
    verified = AnswerVerifier(
        ScriptedLLM({"verdicts": [{"claim_id": "claim_1", "status": "contradicted"}]})
    ).verify(packet, [chunk], [])
    assert not verified.packet.claims
    assert "has no garrison" not in verified.packet.answer_markdown
    assert verified.verification.claims_removed == 1


def test_fake_document_and_marker_are_dropped(chunk):
    packet = compose(chunk)
    packet.citations[0].doc_id = "made_up"
    packet.answer_markdown += "\n[FIG:fake]"
    verified = AnswerVerifier().verify(packet, [chunk], [])
    assert not verified.packet.citations and not verified.packet.claims
    assert "[FIG:fake]" not in verified.packet.answer_markdown
    assert verified.verification.citations_dropped == 1
    assert verified.verification.markers_stripped == 1


def test_bad_bbox_is_removed_without_losing_citation(chunk):
    packet = compose(chunk)
    packet.citations[0].bbox = [0, 0, 999, 999]
    verified = AnswerVerifier().verify(packet, [chunk], [], page_bounds={("plate", 1): (600, 800)})
    assert verified.packet.citations[0].bbox is None
    assert len(verified.packet.citations) == 1


def test_entailment_outage_is_visible_and_capped(chunk):
    packet = compose(chunk, text="The citadel has 3,695 soldiers.")
    verified = AnswerVerifier().verify(packet, [chunk], [])
    assert verified.verification.entailment_skipped
    assert verified.packet.confidence <= 0.6
    assert any(w.action == "verification_skipped" for w in verified.packet.warnings)


def test_dedup_keeps_authority_and_distinct_values(chunk):
    copy = chunk.model_copy(update={"chunk_id": "wiki:c1", "doc_id": "wiki", "authority_tier": 2})
    decoy = copy.model_copy(
        update={"chunk_id": "wiki:c2", "text": chunk.text.replace("3,695", "1,096")}
    )
    result = merge_evidence([copy, decoy, chunk], detector=lambda chunks: [])
    assert {c.chunk_id for c in result.chunks} == {chunk.chunk_id, decoy.chunk_id}


def test_p1_conflict_hook_and_inline_resolution(chunk):
    conflict = Conflict(
        attribute="garrison",
        claim_a="3,695",
        sources_a=["plate:c1"],
        tier_a=1,
        claim_b="1,096",
        sources_b=["wiki:c2"],
        tier_b=2,
        resolution="higher_tier",
        rationale="Prefer the tier-1 plate.",
    )
    bundle = merge_evidence([chunk], detector=lambda chunks: [conflict])
    packet = AnswerComposer().compose(
        "Garrison?", bundle, [], trace_id="test", mode="rich", missing=[], partial=True
    )
    assert "Sources disagree" in packet.answer_markdown
    assert "Prefer the tier-1 plate" in packet.answer_markdown


def test_marker_syntax_in_quoted_corpus_cannot_create_visuals(chunk):
    chunk.text = "The decree says [FIG:fake] must be displayed."
    packet = compose(chunk)
    verified = AnswerVerifier().verify(packet, [chunk], [])
    assert "[FIG:fake]" not in verified.packet.answer_markdown
    assert not verified.packet.visuals
    assert verified.packet.citations[0].excerpt == chunk.text


def test_table_question_does_not_require_an_image_asset(chunk):
    chunk.text = "| House | Year |\n| --- | --- |\n| Greyfell | 412 |"
    packet = compose(chunk, requires_visual=True)
    assert packet.claims and chunk.text in packet.answer_markdown


def test_true_background_statement_does_not_complete_a_year_question(chunk):
    chunk = chunk.model_copy(update={"text": "The forging date is not established."})
    llm = ScriptedLLM(
        {
            "claims": [
                {"text": chunk.text, "sources": [{"chunk_id": chunk.chunk_id, "quote": chunk.text}]}
            ]
        }
    )
    packet = AnswerComposer(llm).compose(
        "In which year was the artifact forged?",
        Bundle(chunks=[chunk]),
        [],
        trace_id="year",
        mode="agent",
        missing=[],
        partial=False,
    )
    assert packet.partial
    assert "The requested year has not been established." in packet.missing_information


def test_composer_missing_information_cannot_be_marked_complete(chunk):
    llm = ScriptedLLM(
        {
            "claims": [
                {"text": chunk.text, "sources": [{"chunk_id": chunk.chunk_id, "quote": chunk.text}]}
            ],
            "missing_information": ["The reason for this assignment is not recorded."],
        }
    )
    packet = AnswerComposer(llm).compose(
        "Why was this garrison assigned?",
        Bundle(chunks=[chunk]),
        [],
        trace_id="missing",
        mode="agent",
        missing=[],
        partial=False,
    )
    assert packet.partial and packet.missing_information
