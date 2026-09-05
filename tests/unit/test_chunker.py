"""Tests for structure-aware chunking.

The three rules are contract tests, not preferences. Breaking any of them produces
chunks that cannot answer a question however good retrieval is, so they are asserted
directly rather than inferred from output quality.
"""

from __future__ import annotations

import json

import pytest

from src.api.schemas import Block
from src.core.config import get_settings
from src.ingestion.adapters.base import estimate_tokens
from src.ingestion.chunker import (
    MIN_TOKENS,
    TARGET_TOKENS,
    chunk_document,
    split_long_block,
)

CHUNKS = get_settings().index_dir / "chunks.jsonl"


def _block(order: int, text: str, block_type="text", section=None) -> Block:
    return Block(
        block_id=f"d:p1:b{order}",
        doc_id="d",
        page=1,
        order=order,
        block_type=block_type,
        text=text,
        section_path=section or ["S"],
        token_count=estimate_tokens(text),
    )


def _chunks(blocks, **kwargs):
    return chunk_document(blocks, "d", 2, "wiki", **kwargs)


# --------------------------------------------------------------------------
# Rule 1 - tables are atomic
# --------------------------------------------------------------------------


def test_a_table_is_never_split_across_chunks() -> None:
    table = "| Field | Value |\n|---|---|\n" + "\n".join(f"| row{i} | {i} |" for i in range(400))
    blocks = [_block(0, "prose " * 100), _block(1, table, "table"), _block(2, "more prose")]
    chunks = _chunks(blocks)

    holding = [c for c in chunks if "| row0 |" in c.text]
    assert len(holding) == 1, "the table appears in exactly one chunk"
    assert "| row399 |" in holding[0].text, "and that chunk holds all of it"
    assert "| Field | Value |" in holding[0].text, "including its header"


def test_an_oversized_table_still_stays_whole() -> None:
    """Rule 1 outranks the token target, deliberately."""
    huge = "| a | b |\n|---|---|\n" + "\n".join(f"| {i} | x |" for i in range(2000))
    chunks = _chunks([_block(0, huge, "table")])
    assert len(chunks) == 1
    assert chunks[0].token_count > TARGET_TOKENS


def test_a_table_is_not_merged_with_surrounding_prose() -> None:
    blocks = [
        _block(0, "before"),
        _block(1, "| a | b |\n|---|---|\n| 1 | 2 |", "table"),
        _block(2, "after"),
    ]
    table_chunk = next(c for c in _chunks(blocks) if "| 1 | 2 |" in c.text)
    assert "before" not in table_chunk.text
    assert "after" not in table_chunk.text


# --------------------------------------------------------------------------
# Rule 2 - section boundaries
# --------------------------------------------------------------------------


def test_chunks_never_span_two_sections() -> None:
    blocks = [
        _block(0, "alpha " * 50, section=["A"]),
        _block(1, "beta " * 50, section=["B"]),
    ]
    for chunk in _chunks(blocks):
        assert not ("alpha" in chunk.text and "beta" in chunk.text)


def test_section_path_is_carried_onto_the_chunk() -> None:
    chunks = _chunks([_block(0, "text " * 60, section=["Vol II", "Chapter 4"])])
    assert chunks[0].section_path == ["Vol II", "Chapter 4"]


# --------------------------------------------------------------------------
# Sizing
# --------------------------------------------------------------------------


def test_no_chunk_exceeds_the_target() -> None:
    """The overlap carry used to drag a whole 510-token block across to satisfy a
    90-token budget, producing 1,078-token chunks against a 600 target."""
    blocks = [_block(i, f"sentence number {i}. " * 40) for i in range(12)]
    for chunk in _chunks(blocks):
        assert chunk.token_count <= TARGET_TOKENS


def test_a_single_long_block_is_split_at_sentence_boundaries() -> None:
    long_text = " ".join(f"This is sentence number {i}." for i in range(400))
    parts = split_long_block(_block(0, long_text), 200)
    assert len(parts) > 1
    assert all(p.token_count <= 200 for p in parts[:-1])
    # Nothing is lost and nothing is duplicated.
    assert "".join(p.text for p in parts).count("This is sentence number 0.") == 1


def test_tables_are_exempt_from_splitting() -> None:
    table = "| a | b |\n" + "\n".join(f"| {i} | y |" for i in range(500))
    assert len(split_long_block(_block(0, table, "table"), 100)) == 1


def test_no_chunk_is_a_useless_fragment() -> None:
    blocks = [_block(0, "Heading", "heading"), _block(1, "body " * 100)]
    chunks = _chunks(blocks)
    assert all(c.token_count >= MIN_TOKENS for c in chunks)
    assert any("Heading" in c.text for c in chunks), "the heading is kept, not dropped"


# --------------------------------------------------------------------------
# Against the real index
# --------------------------------------------------------------------------

built = pytest.mark.skipif(
    not CHUNKS.exists(), reason="run `python -m src.ingestion.chunker` first"
)


@pytest.fixture(scope="module")
def corpus_chunks():
    if not CHUNKS.exists():
        pytest.skip("chunks not built")
    return [
        json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@built
def test_corpus_chunks_respect_the_target(corpus_chunks) -> None:
    oversized = [c for c in corpus_chunks if c["token_count"] > TARGET_TOKENS]
    # Only an atomic table may exceed the target, by rule 1.
    assert all(
        len(c["block_ids"]) == 1 for c in oversized
    ), f"{len(oversized)} multi-block chunks over target"


@built
def test_corpus_chunks_are_essentially_free_of_fragments(corpus_chunks) -> None:
    """Sub-minimum chunks exist only where the alternative is losing corpus text.

    A short paragraph stranded before a table cannot be folded into it (rule 1), so it
    is emitted alone rather than dropped. Losing archive content silently is a far worse
    failure than indexing two small chunks, but the count is asserted so the trade-off
    cannot quietly grow.
    """
    fragments = [c for c in corpus_chunks if c["token_count"] < MIN_TOKENS]
    ids = [c["chunk_id"] for c in fragments[:5]]
    assert len(fragments) <= 5, f"{len(fragments)} fragments, e.g. {ids}"


@built
def test_every_chunk_carries_retrieval_metadata(corpus_chunks) -> None:
    for chunk in corpus_chunks:
        assert 1 <= chunk["authority_tier"] <= 5
        assert chunk["source_type"]
        assert chunk["text"].strip()


@built
def test_the_seventy_image_chunks_are_present_and_standalone(corpus_chunks) -> None:
    images = [c for c in corpus_chunks if c["chunk_id"].startswith("img:")]
    assert len(images) == 70
    assert all(c["asset_ids"] for c in images)


@built
def test_the_emberdeep_chunk_keeps_its_label_binding(corpus_chunks) -> None:
    """The whole 1A path depends on this surviving into the index."""
    chunk = next(
        c for c in corpus_chunks if "emberdeep" in c["doc_id"] and c["chunk_id"].startswith("img:")
    )
    assert "Emberdeep: 1,114" in chunk["text"] or "Emberdeep: 1114" in chunk["text"]
    assert "6,000" in chunk["text"], "reference bars are kept, but separately labelled"
