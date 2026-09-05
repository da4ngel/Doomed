"""DOCX → Blocks, and heading donation to a paired PDF.

WHY this adapter exists twice over:

1. As a primary adapter for the 38 unpaired DOCX documents.
2. As a **structure donor** for the 7 documents that also ship as PDF. Word carries
   explicit heading styles and real table objects, which beat anything recoverable from a
   PDF by font-size clustering. `Heading 2` appears exactly 15 times in Volume II - its
   15 chapters - so the donated outline is ground truth for the PDF heuristic.

WHY tables are read from `document.tables` rather than from paragraphs: `python-docx`
paragraph iteration silently skips table cell text. That is not a small omission - the
codex gazetteer lost 8% of its content that way, which looked like the PDF being richer
when in fact the extraction was wrong.
"""

from __future__ import annotations

from pathlib import Path

from src.api.schemas import Block
from src.ingestion.adapters.base import is_caption, make_block, rows_to_markdown

#: Word's built-in heading styles, in depth order.
HEADING_STYLES = ("Heading 1", "Heading 2", "Heading 3", "Heading 4", "Heading 5")


def _heading_level(style_name: str) -> int | None:
    """Depth for a style name, or None when it is body text."""
    if style_name == "Title":
        return 0
    if style_name in HEADING_STYLES:
        return HEADING_STYLES.index(style_name) + 1
    return None


def _iter_body(document):
    """Yield ('paragraph', p) and ('table', t) in true document order.

    Neither `document.paragraphs` nor `document.tables` alone preserves interleaving, and
    a table detached from the heading above it loses the context that makes it findable.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    parent = document.element.body
    for child in parent.iterchildren():
        if child.tag.endswith("}p"):
            yield "paragraph", Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield "table", Table(child, document)


def extract_outline(path: Path) -> list[tuple[int, str]]:
    """(depth, text) for every heading. Used to donate structure to a paired PDF."""
    import docx

    document = docx.Document(path)
    outline: list[tuple[int, str]] = []
    for paragraph in document.paragraphs:
        level = _heading_level(paragraph.style.name)
        if level is not None and paragraph.text.strip():
            outline.append((level, paragraph.text.strip()))
    return outline


def extract_blocks(path: Path, doc_id: str) -> tuple[list[Block], list[int]]:
    """Extract blocks from a DOCX. Page numbers are unavailable, so page is always 1.

    Returns the same (blocks, scanned_pages) shape as the PDF adapter so the pipeline
    treats every format identically; a DOCX never needs OCR, hence the empty list.
    """
    import docx

    document = docx.Document(path)
    blocks: list[Block] = []
    section: list[str] = []
    order = 0
    paragraph_buffer: list[str] = []

    def flush() -> None:
        nonlocal paragraph_buffer, order
        if not paragraph_buffer:
            return
        text = "\n\n".join(paragraph_buffer)
        blocks.append(
            make_block(
                doc_id,
                1,
                order,
                "caption" if is_caption(text) else "text",
                text,
                section_path=section,
            )
        )
        order += 1
        paragraph_buffer = []

    for kind, item in _iter_body(document):
        if kind == "paragraph":
            text = item.text.strip()
            if not text:
                continue
            level = _heading_level(item.style.name)
            if level is not None:
                flush()
                section = section[:level] + [text]
                blocks.append(make_block(doc_id, 1, order, "heading", text, section_path=section))
                order += 1
            else:
                paragraph_buffer.append(text)
        else:
            flush()
            rows = [[cell.text for cell in row.cells] for row in item.rows]
            markdown = rows_to_markdown(rows)
            if markdown:
                # A table is one atomic block. The chunker will never split it, because
                # half a table cannot answer a question about the other half.
                blocks.append(make_block(doc_id, 1, order, "table", markdown, section_path=section))
                order += 1

    flush()
    return blocks, []
