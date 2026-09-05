"""Plain text → Blocks, for the 41 unpaired ephemera `.txt` documents.

These are in-world letters, ledgers and transcripts with no markup at all, so structure
comes from blank lines and nothing else. That is fine: they are short, and the corpus
README warns their authors "are not always reliable" - what matters for these is the tier
assignment and the citation, not a section hierarchy.

WHY the first line becomes a heading only when it looks like one: an in-world letter
often opens with a salutation, and promoting "To the Warden of Fenspire," to a section
title would produce a nonsense `section_path` on every citation.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.api.schemas import Block
from src.ingestion.adapters.base import is_caption, make_block

#: A short line with no terminal punctuation, in title or upper case, reads as a heading.
_SENTENCE_END = re.compile(r"[.!?,;:]\s*$")


def looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    if _SENTENCE_END.search(stripped):
        return False
    words = stripped.split()
    if len(words) > 12:
        return False
    return stripped.isupper() or stripped == stripped.title()


def extract_blocks(path: Path, doc_id: str) -> tuple[list[Block], list[int]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    blocks: list[Block] = []
    section: list[str] = []
    order = 0

    for paragraph in paragraphs:
        lines = paragraph.split("\n")
        if len(lines) == 1 and looks_like_heading(lines[0]):
            section = [lines[0].strip()]
            blocks.append(make_block(doc_id, 1, order, "heading", lines[0], section_path=section))
            order += 1
            continue

        blocks.append(
            make_block(
                doc_id,
                1,
                order,
                "caption" if is_caption(paragraph) else "text",
                paragraph,
                section_path=section,
            )
        )
        order += 1

    return blocks, []
