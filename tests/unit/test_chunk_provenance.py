"""Provenance tests: a chunk's text must be accounted for by the blocks it names.

A chunk that carries text from blocks it does not list produces a citation where every
field validates — real chunk_id, real doc_id, real page — but the quoted words are not in
the cited blocks. That is a fabricated citation that no schema check can catch, which is
why it gets its own test file rather than living among the sizing assertions.
"""

from __future__ import annotations

import json

import pytest

from src.api.schemas import Block
from src.core.config import get_settings
from src.ingestion.adapters.base import estimate_tokens
from src.ingestion.chunker import chunk_document

CHUNKS = get_settings().index_dir / "chunks.jsonl"
BLOCKS = get_settings().index_dir / "blocks.jsonl"


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


def test_a_carried_fragment_brings_its_block_ids_with_it() -> None:
    """The exact shape that produced the bug: a short paragraph stranded before a table,
    held back, then prepended to the next chunk."""
    blocks = [
        _block(0, "stranded"),
        _block(1, "| a | b |\n|---|---|\n| 1 | 2 |", "table"),
        _block(2, "body " * 200),
    ]
    chunks = chunk_document(blocks, "d", 2, "wiki")
    holder = next(c for c in chunks if "stranded" in c.text)
    assert "d:p1:b0" in holder.block_ids, "the carried text's block must be listed"


def test_every_chunk_lists_a_block_for_all_its_text() -> None:
    blocks = [_block(0, "tiny"), _block(1, "prose " * 300), _block(2, "more " * 300)]
    by_id = {b.block_id: b for b in blocks}
    for chunk in chunk_document(blocks, "d", 2, "wiki"):
        listed = sum(by_id[b].token_count for b in chunk.block_ids if b in by_id)
        # Overlap and joining whitespace mean the counts are not identical, but the
        # listed blocks must plausibly account for the text rather than falling short.
        assert listed >= chunk.token_count * 0.6, chunk.chunk_id


# --------------------------------------------------------------------------
# Against the real index
# --------------------------------------------------------------------------

built = pytest.mark.skipif(not CHUNKS.exists() or not BLOCKS.exists(), reason="index not built")


@pytest.fixture(scope="module")
def corpus():
    if not CHUNKS.exists() or not BLOCKS.exists():
        pytest.skip("index not built")
    chunks = [json.loads(x) for x in CHUNKS.read_text(encoding="utf-8").splitlines() if x.strip()]
    blocks = {}
    for line in BLOCKS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            block = json.loads(line)
            blocks[block["block_id"]] = block
    return chunks, blocks


@built
def test_no_corpus_chunk_carries_unattributed_text(corpus) -> None:
    """Every chunk's token count must be explicable by the blocks it names.

    Split blocks get a `.N` suffix and image chunks reference an asset id rather than a
    block, so both are resolved to their parent before comparing.
    """
    chunks, blocks = corpus
    offenders = []
    for chunk in chunks:
        if chunk["chunk_id"].startswith("img:"):
            continue
        listed = 0
        for block_id in chunk["block_ids"]:
            block = blocks.get(block_id) or blocks.get(block_id.rsplit(".", 1)[0])
            if block:
                listed += block["token_count"]
        if listed < chunk["token_count"] * 0.6:
            offenders.append((chunk["chunk_id"], chunk["token_count"], listed))

    assert not offenders, f"{len(offenders)} chunks with unattributed text: {offenders[:3]}"


@built
def test_every_block_id_on_a_chunk_resolves(corpus) -> None:
    """A citation naming a block that does not exist is unverifiable."""
    chunks, blocks = corpus
    dangling = [
        block_id
        for chunk in chunks
        if not chunk["chunk_id"].startswith("img:")
        for block_id in chunk["block_ids"]
        if block_id not in blocks and block_id.rsplit(".", 1)[0] not in blocks
    ]
    assert not dangling, f"{len(dangling)} dangling block ids, e.g. {dangling[:3]}"
