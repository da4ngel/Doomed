"""Shared helpers for the format adapters.

Every adapter returns `list[Block]` against the frozen schema, so the chunker and the
indexer never learn what format a document came from. That is the whole point of the
adapter layer: format knowledge stops here.
"""

from __future__ import annotations

import hashlib
import re

from src.api.schemas import Block, BlockType
from src.core.tokens import TOKENIZER_USED, estimate_tokens  # noqa: F401 - re-export

#: `Fig. 3`, `Plate IV`, `Table 12` - used to bind a caption to the figure above it.
CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?\.?|plate|table)\s+([ivxlc]+|\d+)\b", re.IGNORECASE)

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Collapse runs of spaces and blank lines without destroying paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def block_checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def is_caption(text: str) -> bool:
    return bool(CAPTION_RE.match(text.strip()))


def make_block(
    doc_id: str,
    page: int,
    order: int,
    block_type: BlockType,
    text: str,
    *,
    section_path: list[str] | None = None,
    bbox: list[float] | None = None,
    asset_path: str | None = None,
    caption_ref: str | None = None,
    ocr_confidence: float | None = None,
) -> Block:
    """Build a Block with the derived fields filled in consistently."""
    text = clean_text(text)
    return Block(
        block_id=f"{doc_id}:p{page}:b{order}",
        doc_id=doc_id,
        page=page,
        order=order,
        block_type=block_type,
        text=text,
        asset_path=asset_path,
        bbox=bbox,
        section_path=list(section_path or []),
        caption_ref=caption_ref,
        ocr_confidence=ocr_confidence,
        token_count=estimate_tokens(text),
        checksum=block_checksum(text),
    )


def rows_to_markdown(rows: list[list[str]]) -> str:
    """Render a table as markdown so it survives as one readable unit in a chunk.

    Tables are never split across chunks, so this string is what a model actually sees
    when it is asked about a table - keeping the header row attached is the point.
    """
    cleaned = [[(cell or "").strip().replace("\n", " ") for cell in row] for row in rows if row]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header, *body = cleaned
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)
