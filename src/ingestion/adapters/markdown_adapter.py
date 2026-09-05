"""Markdown → Blocks, for the 95 wiki articles.

WHY the Infobox stays one block: it is the densest, most answerable object in the whole
corpus - `| Garrison strength | 2598 |` is a fact per row. Splitting it across chunks
would strand rows from their header and make the table unreadable to a model, which is
the same failure the chunker's table rule exists to prevent.

The graph is extracted separately by `src/graph/wiki_extract.py`; this adapter only
produces retrievable text. Both read the same file, deliberately - the graph needs
relations, retrieval needs prose, and forcing one pass to serve both would compromise
each.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.api.schemas import Block
from src.ingestion.adapters.base import is_caption, make_block

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_IMAGE_ONLY = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")


def extract_blocks(path: Path, doc_id: str) -> tuple[list[Block], list[int]]:
    """Parse a markdown document into heading, table and text blocks."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    blocks: list[Block] = []
    section: list[str] = []
    order = 0
    buffer: list[str] = []
    table: list[str] = []

    def flush_text() -> None:
        nonlocal buffer, order
        body = "\n".join(buffer).strip()
        buffer = []
        if not body:
            return
        blocks.append(
            make_block(
                doc_id,
                1,
                order,
                "caption" if is_caption(body) else "text",
                body,
                section_path=section,
            )
        )
        order += 1

    def flush_table() -> None:
        nonlocal table, order
        if not table:
            return
        body = "\n".join(table).strip()
        table = []
        blocks.append(make_block(doc_id, 1, order, "table", body, section_path=section))
        order += 1

    for line in lines:
        heading = _HEADING.match(line)
        if heading:
            flush_table()
            flush_text()
            depth = len(heading.group(1)) - 1
            title = heading.group(2).strip()
            section = section[:depth] + [title]
            blocks.append(make_block(doc_id, 1, order, "heading", title, section_path=section))
            order += 1
            continue

        if _TABLE_ROW.match(line):
            flush_text()
            table.append(line.strip())
            continue

        if table:
            flush_table()

        if _IMAGE_ONLY.match(line):
            # The image itself is handled by src/ingestion/images.py, which already has a
            # VLM description and an entity link for it. Repeating the markdown here would
            # put a bare filename in the index with no retrievable content.
            continue

        buffer.append(line)

    flush_table()
    flush_text()
    return blocks, []
