"""Tests for the format adapters and the ingestion pipeline.

Each adapter is checked on a synthetic fixture for behaviour and against the real corpus
for the properties the retrieval layer depends on - a table that survives intact, a
section path that names a real place, a bbox that can be turned into a page crop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.config import CORPUS_ROOT
from src.ingestion.adapters import markdown_adapter, text_adapter
from src.ingestion.adapters.base import estimate_tokens, is_caption, rows_to_markdown
from src.ingestion.pipeline import looks_like_markdown

corpus = pytest.mark.skipif(not CORPUS_ROOT.exists(), reason="corpus not present")


# --------------------------------------------------------------------------
# base helpers
# --------------------------------------------------------------------------


def test_caption_patterns() -> None:
    assert is_caption("Figure 3 - the seal variants")
    assert is_caption("Plate IV: Concord seals")
    assert is_caption("Table 12 lists the garrisons")
    assert not is_caption("The figure of a man stood in the doorway")


def test_rows_to_markdown_keeps_the_header_attached() -> None:
    table = rows_to_markdown([["Field", "Value"], ["Born", "315 AS"]])
    assert table.splitlines()[0] == "| Field | Value |"
    assert "| Born | 315 AS |" in table


def test_rows_to_markdown_pads_ragged_rows() -> None:
    table = rows_to_markdown([["a", "b", "c"], ["x"]])
    assert all(line.count("|") == 4 for line in table.splitlines())


def test_estimate_tokens_is_positive_and_scales() -> None:
    assert estimate_tokens("hello") >= 1
    assert estimate_tokens("word " * 200) > estimate_tokens("word " * 10)


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------

MD = """![Portrait](images/atmo_portrait_character_x.png)

# Aldous Wrenfield

Some prose about Aldous.

## Infobox

| Field | Value |
|---|---|
| Born | 315 AS |
| Member of | The Iron-Ring Cartel |

## History

More prose.
"""


def test_markdown_keeps_the_infobox_as_one_block(tmp_path: Path) -> None:
    """A row separated from its header is unreadable; the infobox is the densest,
    most answerable object in the corpus."""
    path = tmp_path / "a.md"
    path.write_text(MD, encoding="utf-8")
    blocks, _ = markdown_adapter.extract_blocks(path, "a")
    tables = [b for b in blocks if b.block_type == "table"]
    assert len(tables) == 1
    assert "| Born | 315 AS |" in tables[0].text
    assert "| Member of | The Iron-Ring Cartel |" in tables[0].text


def test_markdown_builds_a_section_path(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text(MD, encoding="utf-8")
    blocks, _ = markdown_adapter.extract_blocks(path, "a")
    infobox = next(b for b in blocks if b.block_type == "table")
    assert infobox.section_path == ["Aldous Wrenfield", "Infobox"]


def test_markdown_drops_bare_image_lines(tmp_path: Path) -> None:
    """Images are handled by the image pipeline, which has a VLM description for each.
    Repeating the markdown here would index a filename with no retrievable content."""
    path = tmp_path / "a.md"
    path.write_text(MD, encoding="utf-8")
    blocks, _ = markdown_adapter.extract_blocks(path, "a")
    assert not any("atmo_portrait" in b.text for b in blocks)


# --------------------------------------------------------------------------
# plain text
# --------------------------------------------------------------------------


def test_text_adapter_does_not_promote_a_salutation_to_a_heading(tmp_path: Path) -> None:
    """An in-world letter opens with a salutation; treating it as a section title would
    put nonsense in every citation from that document."""
    path = tmp_path / "letter.txt"
    path.write_text("To the Warden of Fenspire,\n\nI write concerning the matter.\n", "utf-8")
    blocks, _ = text_adapter.extract_blocks(path, "letter")
    assert all(b.block_type != "heading" for b in blocks)


def test_text_adapter_recognises_a_real_heading(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("MUSTER ROLL\n\nThe following are recorded.\n", "utf-8")
    blocks, _ = text_adapter.extract_blocks(path, "note")
    assert blocks[0].block_type == "heading"


def test_markdown_detection_routes_txt_correctly(tmp_path: Path) -> None:
    """All 46 ephemera .txt files are really markdown; routing by extension alone
    would discard 86 headings and 68 table rows."""
    md = tmp_path / "a.txt"
    md.write_text("# Title\n\nbody\n", encoding="utf-8")
    plain = tmp_path / "b.txt"
    plain.write_text("Just some prose with no markup at all.\n", encoding="utf-8")
    assert looks_like_markdown(md)
    assert not looks_like_markdown(plain)


# --------------------------------------------------------------------------
# against the real corpus
# --------------------------------------------------------------------------


@corpus
def test_every_ephemera_txt_is_markdown() -> None:
    txts = sorted((CORPUS_ROOT / "ephemera").glob("*.txt"))
    assert txts
    assert all(looks_like_markdown(p) for p in txts)


@corpus
def test_pdf_headings_are_siblings_not_nested_chapters() -> None:
    """Volume II's 26pt title sits on a page with no text layer. Ranking depth against
    the document-wide size list made Chapter 2 a child of Chapter 1."""
    from src.ingestion.adapters import pdf_adapter

    path = CORPUS_ROOT / "chronicles/the_ashen_chronicles_volume_ii_the_long_reprisal.pdf"
    blocks, _ = pdf_adapter.extract_blocks(path, "v2")
    chapters = [b for b in blocks if b.block_type == "heading" and b.text.startswith("Chapter")]
    assert len(chapters) == 15
    assert all(len(b.section_path) == 1 for b in chapters)


@corpus
def test_pdf_blocks_carry_page_and_bbox_for_citations() -> None:
    from src.ingestion.adapters import pdf_adapter

    path = CORPUS_ROOT / "chronicles/the_ashen_chronicles_volume_ii_the_long_reprisal.pdf"
    blocks, _ = pdf_adapter.extract_blocks(path, "v2")
    text_blocks = [b for b in blocks if b.block_type == "text"]
    assert text_blocks
    for block in text_blocks[:20]:
        assert block.page >= 1
        assert block.bbox and len(block.bbox) == 4
        assert block.bbox[2] > block.bbox[0] and block.bbox[3] > block.bbox[1]


@corpus
def test_bold_subheadings_are_found_where_size_gives_no_signal() -> None:
    """The Annals has only two font sizes above body text, so its sub-headings are
    detectable by weight alone. Before this, 19 of 82 headings were lost."""
    from src.ingestion.adapters import docx_adapter, pdf_adapter

    outline = docx_adapter.extract_outline(CORPUS_ROOT / "codex/the_annals_of_the_ashen_era.docx")
    blocks, _ = pdf_adapter.extract_blocks(
        CORPUS_ROOT / "codex/the_annals_of_the_ashen_era.pdf", "annals"
    )
    found = {b.text.strip().lower() for b in blocks if b.block_type == "heading"}
    declared = {t.strip().lower() for _, t in outline}
    assert len(declared & found) >= 80, f"only {len(declared & found)} of {len(declared)}"


@corpus
def test_docx_tables_are_read_from_table_objects() -> None:
    """python-docx paragraph iteration silently skips table cells - the codex lost 8%
    of its content that way, which looked like the PDF being richer."""
    from src.ingestion.adapters import docx_adapter

    blocks, _ = docx_adapter.extract_blocks(
        CORPUS_ROOT / "codex/codex_vaeloria_i_gazetteer_of_the_sundered_realms.docx", "cx1"
    )
    tables = [b for b in blocks if b.block_type == "table"]
    assert len(tables) == 28
    assert any("Garrison strength" in t.text for t in tables)


# --------------------------------------------------------------------------
# tokenizer provenance
# --------------------------------------------------------------------------


def test_tiktoken_is_the_counter_actually_in_use() -> None:
    """The reported chunk counts assume tiktoken. Prove it, do not hope for it."""
    from src.ingestion.adapters import base

    base.estimate_tokens("the ashen era")
    assert base.TOKENIZER_USED == "tiktoken-cl100k_base", (
        f"this build counted tokens with {base.TOKENIZER_USED}; every chunk count "
        "and retrieval metric it produces is incomparable with a tiktoken build"
    )


def test_the_estimate_fallback_announces_itself(monkeypatch, caplog) -> None:
    """A silent fallback changes the chunk count from identical inputs.

    Two builders reported 2,474 and 2,487 chunks from the same corpus and the same
    chunker code, and neither could tell which denominator either build had used,
    because tiktoken downloads its BPE table on first use and fails quietly offline.
    """
    import logging

    from src.ingestion.adapters import base

    monkeypatch.setattr(base, "_ENCODING", None)
    monkeypatch.setattr(base, "TOKENIZER_USED", "unknown")
    monkeypatch.setattr(base, "_encoding", lambda: (_ for _ in ()).throw(RuntimeError("offline")))

    with caplog.at_level(logging.WARNING):
        assert base.estimate_tokens("x" * 400) == 100

    assert base.TOKENIZER_USED == "char-estimate"
    assert any(
        "ESTIMATE" in r.message for r in caplog.records
    ), "the fallback must warn - that is the entire point of this change"

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        base.estimate_tokens("y" * 400)
    assert not caplog.records, "warn once per process, not once per block"
