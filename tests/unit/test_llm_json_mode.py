"""OpenAI's JSON mode refuses a prompt that never says "json".

This is not a style nit. A6's entailment prompt showed the exact shape it wanted -
{"verdicts":[{"claim_id":"...","status":"entailed|unsupported|contradicted"}]} - and
never contained the word. Every entailment call returned:

    400: 'messages' must contain the word 'json' in some form, to use
         'response_format' of type 'json_object'.

The verifier caught that as `entailment_skipped` and downgraded every non-extractive
claim to "Inference (not verified)", so a full 20-question run showed groundedness 0.0
on every multi-hop and contradiction answer while the answers themselves were right.
A verification step that silently stops verifying is worse than one that fails loudly.
"""

from __future__ import annotations

from src.core.llm import _require_json_word


def test_a_prompt_showing_json_shape_but_not_saying_json_is_amended() -> None:
    """The exact A6 case: a JSON literal in the text, no the word itself."""
    messages = [
        {
            "role": "system",
            "content": 'Return {"verdicts":[{"claim_id":"...","status":"entailed"}]}.',
        },
        {"role": "user", "content": "<evidence>...</evidence>"},
    ]

    _require_json_word(messages)

    assert any(
        "json" in m["content"].lower() for m in messages
    ), "OpenAI rejects json_object unless the word appears somewhere in the messages"
    assert len(messages) == 2, "the note belongs on the existing system message"


def test_a_prompt_that_already_says_json_is_left_alone() -> None:
    """Untouched prompts keep their cache keys, so recorded runs stay reproducible."""
    messages = [
        {"role": "system", "content": "Reply as a JSON object."},
        {"role": "user", "content": "<evidence>...</evidence>"},
    ]
    before = [dict(m) for m in messages]

    _require_json_word(messages)

    assert messages == before


def test_the_word_counts_wherever_it_appears() -> None:
    """OpenAI scans every message, not just the system one."""
    messages = [
        {"role": "system", "content": "Answer only from evidence."},
        {"role": "user", "content": "Return json please."},
    ]
    before = [dict(m) for m in messages]

    _require_json_word(messages)

    assert messages == before


def test_a_multimodal_prompt_gains_a_system_message_rather_than_mutating_parts() -> None:
    """Vision calls carry list content. Appending a string to a list would corrupt the
    request, so the note is prepended as its own message instead."""
    messages = [{"role": "user", "content": [{"type": "text", "text": "Describe this plate."}]}]

    _require_json_word(messages)

    assert messages[0] == {"role": "system", "content": "Respond with a single JSON object."}
    assert isinstance(messages[1]["content"], list), "the original parts are untouched"


def test_no_system_message_still_gets_the_word() -> None:
    messages = [{"role": "user", "content": "List the garrison strengths."}]

    _require_json_word(messages)

    assert any("json" in str(m["content"]).lower() for m in messages)


def test_a_vision_call_refuses_to_run_without_a_vision_model(tmp_path) -> None:
    """An unset LLM_MODEL_VISION used to fall through to the synthesis model in silence.

    On a fresh clone following .env.example that is `deepseek/deepseek-chat`, which
    cannot see an image at all — so every one of the 70 figure descriptions would have
    been produced by a text-only model, and 1A is over half the dev set. Failing loudly
    is the only safe behaviour.
    """
    import pytest

    from src.core.cache import ResponseCache
    from src.core.config import Settings
    from src.core.llm import LLMClient

    client = LLMClient(
        settings=Settings(_env_file=None, llm_model_vision=""),
        cache=ResponseCache(tmp_path / "cache"),
    )
    with pytest.raises(ValueError, match="LLM_MODEL_VISION"):
        client.describe_image(tmp_path / "nope.png", "Describe this plate.")


def test_the_shipped_example_env_names_a_vision_model() -> None:
    """The reproducibility path must work as shipped: a judge who copies .env.example and
    runs `make images` should not silently get a text model."""
    from src.core.config import Settings

    assert Settings(
        _env_file=".env.example"
    ).llm_model_vision, (
        ".env.example must set LLM_MODEL_VISION, or an empty value overrides the default"
    )
