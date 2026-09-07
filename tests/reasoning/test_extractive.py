from src.synthesis.extractive import numeric_figure_draft


def test_only_exact_subject_value_line_can_be_rendered(chunk, asset):
    asset = {
        **asset,
        "values": [
            {"label": "Greyfell Citadel", "value": "3,695"},
            {"label": "Reference garrison", "value": "6,000"},
        ],
    }
    source = chunk.model_copy(
        update={"text": "Garrison strength\nGreyfell Citadel: 3,695\nReference garrison: 6,000"}
    )
    draft = numeric_figure_draft("Greyfell Citadel garrison strength", [source], [asset])
    assert draft.claims[0].text == "Greyfell Citadel: 3,695"
    assert draft.claims[0].sources[0].quote in source.text
    assert numeric_figure_draft("Ironfell Citadel garrison strength", [source], [asset]) is None
    assert numeric_figure_draft("Greyfell Citadel garrison strength", [chunk], [asset]) is None
    assert (
        numeric_figure_draft("Greyfell Citadel garrison strength", [source, source], [asset])
        is None
    )
    assert numeric_figure_draft("Describe Greyfell Citadel", [source], [asset]) is None


def test_verified_numeric_fact_survives_partial_investigation(chunk, asset):
    from src.agents.composer import AnswerComposer
    from src.agents.merger import Bundle
    from tests.reasoning.conftest import ScriptedLLM

    asset = {**asset, "values": [{"label": "Greyfell Citadel", "value": "3,695"}]}
    source = chunk.model_copy(update={"text": "Garrison strength\nGreyfell Citadel: 3,695"})
    llm = ScriptedLLM()
    packet = AnswerComposer(llm).compose(
        "What is Greyfell Citadel garrison strength?",
        Bundle(chunks=[source]),
        [asset],
        trace_id="partial",
        mode="rich",
        missing=["The requested unit is not recorded."],
        partial=True,
        requires_visual=True,
    )
    assert packet.claims[0].text == "Greyfell Citadel: 3,695"
    assert packet.partial and packet.missing_information == ["The requested unit is not recorded."]
    assert not llm.calls
