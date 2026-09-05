"""PDF → Blocks, with page numbers, bounding boxes and section paths.

WHY PyMuPDF over a higher-level extractor: it returns text spans with their font size and
bounding box in one pass. The bbox is not decoration - `Citation.bbox` drives the
page-crop preview, which is how a judge checks a citation is real rather than plausible.

WHY font-size clustering for headings: these PDFs carry **no table of contents** (measured:
0 outline entries on all of them), but font size separates structure cleanly - 26pt title,
15pt heading, 10.5pt body in the novels. So the heading signal is there, just not in the
metadata. The clustering is per-document because point sizes differ between the novels and
the codexes.

Where a DOCX twin exists we prefer its explicit heading styles and only fall back to this;
`pipeline.py` decides. The agreement rate between the two is reported, which turns a
heuristic into a measured claim.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from src.api.schemas import Block
from src.ingestion.adapters.base import is_caption, make_block

log = logging.getLogger(__name__)

#: A page with fewer characters than this has no usable text layer - it is a scan.
#: Same constant the corpus profiler used, so the two agree by construction.
SCANNED_CHAR_THRESHOLD = 50

#: Ignore rare font sizes when deciding heading levels; a single oversized drop-cap is
#: not a section.
MIN_SPANS_FOR_A_HEADING_LEVEL = 2


def _body_size(sizes: Counter[float]) -> float:
    """The most common font size by character volume is the body text."""
    return sizes.most_common(1)[0][0] if sizes else 0.0


def detect_heading_sizes(doc) -> list[float]:
    """Font sizes that plausibly mark headings, largest first.

    Anything meaningfully larger than body text and used more than once. Returns at most
    two levels - deeper nesting is not reliably recoverable from size alone, and a wrong
    section path is worse than a shallow one.
    """
    volume: Counter[float] = Counter()
    occurrences: Counter[float] = Counter()
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = round(span["size"], 1)
                    volume[size] += len(span["text"])
                    occurrences[size] += 1

    if not volume:
        return []
    body = _body_size(volume)
    candidates = [
        size
        for size in occurrences
        if size > body * 1.15 and occurrences[size] >= MIN_SPANS_FOR_A_HEADING_LEVEL
    ]
    return sorted(candidates, reverse=True)[:2]


#: PyMuPDF span flag bit for bold.
_BOLD_FLAG = 1 << 4

#: A fully bold line this short, with no terminal punctuation, is a sub-heading.
_MAX_BOLD_HEADING_CHARS = 80


def _span_lines(page) -> list[tuple[str, float, list[float], bool]]:
    """(text, max font size, bbox, all-bold) per visual line, in reading order."""
    lines: list[tuple[str, float, list[float], bool]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 0 = text
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s["text"].strip()]
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            size = max((round(s["size"], 1) for s in spans), default=0.0)
            bold = bool(spans) and all(s["flags"] & _BOLD_FLAG for s in spans)
            lines.append((text, size, [round(v, 1) for v in line["bbox"]], bold))
    return lines


def _is_bold_heading(text: str, bold: bool) -> bool:
    """Sub-headings that carry no size signal at all.

    The Annals renders "Office and Identification" and "Function" at body size in bold -
    measured, it has only two font sizes above body text, so raising the size-level cap
    could never have found them. Weight is the only signal present.
    """
    if not bold or len(text) > _MAX_BOLD_HEADING_CHARS:
        return False
    return not text.rstrip().endswith((".", ",", ";", ":", "!", "?"))


def extract_blocks(
    path: Path,
    doc_id: str,
    heading_sizes: list[float] | None = None,
    section_path_override: list[str] | None = None,
) -> tuple[list[Block], list[int]]:
    """Extract blocks from a born-digital PDF.

    Returns (blocks, pages_without_a_text_layer). The second value is what routes pages
    to OCR, and it is reported rather than silently handled.
    """
    import pymupdf

    doc = pymupdf.open(path)
    try:
        sizes = heading_sizes if heading_sizes is not None else detect_heading_sizes(doc)
        blocks: list[Block] = []
        scanned_pages: list[int] = []
        section: list[str] = list(section_path_override or [])
        seen_sizes: set[float] = set()
        order = 0

        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            lines = _span_lines(page)
            if sum(len(text) for text, _, _, _ in lines) < SCANNED_CHAR_THRESHOLD:
                scanned_pages.append(page_number)
                continue

            paragraph: list[str] = []
            para_bbox: list[float] | None = None

            def flush(current_section: list[str], page_number: int = page_number) -> None:
                # `current_section` is passed explicitly rather than captured: flush runs
                # just BEFORE section_path is reassigned for a new heading, so a closure
                # over the loop variable would attach the wrong section to the paragraph.
                nonlocal paragraph, para_bbox, order
                if not paragraph:
                    return
                text = " ".join(paragraph)
                blocks.append(
                    make_block(
                        doc_id,
                        page_number,
                        order,
                        "caption" if is_caption(text) else "text",
                        text,
                        section_path=current_section,
                        bbox=para_bbox,
                    )
                )
                order += 1
                paragraph, para_bbox = [], None

            for text, size, bbox, bold in lines:
                size_heading = size in sizes and len(text) < 200
                bold_heading = not size_heading and _is_bold_heading(text, bold)
                if size_heading or bold_heading:
                    flush(section)
                    # Depth is measured against heading sizes actually SEEN so far, not
                    # against the document-wide size list. Volume II's 26pt title sits on
                    # a page with no text layer, so it never appears; ranking against the
                    # static list pushed every chapter to depth 1 and made Chapter 2 a
                    # child of Chapter 1.
                    if size_heading:
                        seen_sizes.add(size)
                        level = sum(1 for s in seen_sizes if s > size)
                    else:
                        # A bold sub-heading nests one level under whatever precedes it.
                        level = len(section)
                    section = section[:level] + [text]
                    blocks.append(
                        make_block(
                            doc_id,
                            page_number,
                            order,
                            "heading",
                            text,
                            section_path=section,
                            bbox=bbox,
                        )
                    )
                    order += 1
                    continue

                paragraph.append(text)
                para_bbox = (
                    bbox
                    if para_bbox is None
                    else [
                        min(para_bbox[0], bbox[0]),
                        min(para_bbox[1], bbox[1]),
                        max(para_bbox[2], bbox[2]),
                        max(para_bbox[3], bbox[3]),
                    ]
                )
            flush(section)

        return blocks, scanned_pages
    finally:
        doc.close()


def page_count(path: Path) -> int:
    import pymupdf

    doc = pymupdf.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()
