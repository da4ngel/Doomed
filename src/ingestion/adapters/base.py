"""Shared helpers for the format adapters.

Every adapter returns `list[Block]` against the frozen schema, so the chunker and the
indexer never learn what format a document came from. That is the whole point of the
adapter layer: format knowledge stops here.
"""

from __future__ import annotations

import hashlib
import logging
import re

from src.api.schemas import Block, BlockType

log = logging.getLogger(__name__)

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


#: Which counter the last ingestion actually used. Read by the build manifest so a
#: chunk count can always be traced to the tokenizer that produced it.
TOKENIZER_USED = "unknown"


def estimate_tokens(text: str) -> int:
    """Token count via tiktoken when available, else a 4-chars-per-token estimate.

    The estimate is a fallback rather than the default because chunk sizing is a reported
    experiment (300/600/1000 sweep) and an approximate denominator would make those
    numbers soft.

    WHY the fallback is now loud: it used to be silent, and it changes the chunk count
    from identical inputs and identical code, because `tiktoken.get_encoding` DOWNLOADS
    its BPE table on first use and fails offline. Two builders reported 2,474 and 2,487
    chunks from the same corpus and neither could tell which denominator either build had
    used. A number that quietly reshapes the index - and therefore every retrieval metric
    computed from it - has to announce itself.
    """
    global TOKENIZER_USED
    try:
        count = len(_encoding().encode(text))
    except Exception as exc:  # noqa: BLE001 - never let token counting break ingestion
        if TOKENIZER_USED != "char-estimate":
            TOKENIZER_USED = "char-estimate"
            log.warning(
                "tiktoken unavailable (%s: %s) - falling back to a 4-chars-per-token "
                "ESTIMATE. Chunk boundaries, and every metric computed from them, will "
                "not match a build made with tiktoken. Install it, or reach the network "
                "once so the BPE table caches, before recording any reported number.",
                type(exc).__name__,
                exc,
            )
        return max(1, len(text) // 4)
    if TOKENIZER_USED == "unknown":
        TOKENIZER_USED = "tiktoken-cl100k_base"
    return count


_ENCODING = None


def _encoding():
    global _ENCODING
    if _ENCODING is None:
        import tiktoken

        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return _ENCODING


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
