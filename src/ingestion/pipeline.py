"""Corpus → documents.jsonl + blocks.jsonl. Resumable, never halts on one bad file.

WHY a dead-letter list instead of an exception: 236 documents in five formats, some of
them scans. One malformed file must not cost the other 235, and hiding the failure is
worse than reporting it - the dead-letter count is a number in the report, and a run that
"succeeded" while silently dropping documents is how eval scores become meaningless.

WHY the adapter is chosen by content and not by extension: all 46 ephemera `.txt` files
are actually markdown, carrying 86 headings and 68 table rows between them. Routing them
by extension to a plain-text adapter would discard every one of those structures.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.api.schemas import Block
from src.core.config import Settings, get_settings
from src.ingestion.adapters import (
    docx_adapter,
    markdown_adapter,
    pdf_adapter,
    text_adapter,
)
from src.ingestion.pairing import LogicalDocument, build_logical_documents, is_scan

log = logging.getLogger(__name__)


def looks_like_markdown(path: Path) -> bool:
    """True when a .txt file is really markdown - measured: all 46 of them are."""
    import re

    head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    return bool(re.search(r"^#{1,6}\s", head, re.M) or re.search(r"^\s*\|.*\|\s*$", head, re.M))


@dataclass
class IngestStats:
    documents: int = 0
    blocks: int = 0
    tables: int = 0
    headings: int = 0
    figures: int = 0
    scanned_pages: int = 0
    documents_needing_ocr: list[str] = field(default_factory=list)
    outline_agreement: list[tuple[str, int, int]] = field(default_factory=list)
    dead_letter: list[dict[str, str]] = field(default_factory=list)

    def agreement_rate(self) -> float:
        """How often PDF font-size clustering found the headings Word declares.

        Reported rather than asserted - the same trick as scan-detection agreement. A
        heuristic with a measured agreement rate is defensible; one without is a guess.
        """
        matched = sum(m for _, m, _ in self.outline_agreement)
        total = sum(t for _, _, t in self.outline_agreement)
        return matched / total if total else 0.0


def _donate_outline(blocks: list[Block], outline: list[tuple[int, str]]) -> int:
    """Correct PDF heading depths using the paired DOCX's declared heading styles.

    Matches on heading text rather than position, so it needs no page mapping. Returns
    how many PDF headings the DOCX confirms.
    """
    depth_by_text = {text.strip().lower(): depth for depth, text in outline}
    matched = 0
    section: list[str] = []
    for block in blocks:
        if block.block_type != "heading":
            block.section_path = list(section)
            continue
        declared = depth_by_text.get(block.text.strip().lower())
        if declared is None:
            section = section[: max(len(section) - 1, 0)] + [block.text]
        else:
            matched += 1
            depth = max(declared - 1, 0)
            section = section[:depth] + [block.text]
        block.section_path = list(section)
    return matched


def _ocr_scanned_pages(path: Path, doc_id: str, pages: list[int]) -> list[Block]:
    """OCR the pages with no text layer. Degrades to nothing when Tesseract is absent."""
    from src.ingestion.adapters.base import make_block
    from src.ingestion.ocr import ocr_image, tesseract_available

    if not tesseract_available() or not pages:
        return []

    import pymupdf

    blocks: list[Block] = []
    doc = pymupdf.open(path)
    try:
        for order, page_number in enumerate(pages):
            page = doc[page_number - 1]
            pixmap = page.get_pixmap(dpi=200)
            temp = Path(get_settings().index_dir) / f".ocr_{doc_id}_{page_number}.png"
            temp.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(temp)
            try:
                result = ocr_image(temp)
            finally:
                temp.unlink(missing_ok=True)
            if result.text.strip():
                blocks.append(
                    make_block(
                        doc_id,
                        page_number,
                        10_000 + order,
                        "text",
                        result.text,
                        ocr_confidence=result.mean_confidence,
                    )
                )
    finally:
        doc.close()
    return blocks


def ingest_document(
    document: LogicalDocument, corpus_root: Path
) -> tuple[list[Block], list[int], int, int]:
    """Extract one logical document. Returns (blocks, scanned_pages, matched, declared)."""
    path = corpus_root / document.canonical_path
    doc_id = document.doc_id
    fmt = document.canonical_format

    if fmt == "pdf":
        blocks, scanned = pdf_adapter.extract_blocks(path, doc_id)
        matched = declared = 0
        donor = document.structure_donor
        if donor:
            outline = docx_adapter.extract_outline(corpus_root / donor)
            if outline:
                matched = _donate_outline(blocks, outline)
                declared = len(outline)
        if scanned:
            blocks.extend(_ocr_scanned_pages(path, doc_id, scanned))
            # OCR blocks are appended after extraction, so restore reading order by
            # page. A recovered title page belongs at the front of the document, not
            # stranded at the end where it becomes a 12-token orphan chunk.
            blocks.sort(key=lambda b: (b.page, b.order))
        return blocks, scanned, matched, declared

    if fmt == "docx":
        blocks, scanned = docx_adapter.extract_blocks(path, doc_id)
        return blocks, scanned, 0, 0

    if fmt == "md" or (fmt == "txt" and looks_like_markdown(path)):
        blocks, scanned = markdown_adapter.extract_blocks(path, doc_id)
        return blocks, scanned, 0, 0

    blocks, scanned = text_adapter.extract_blocks(path, doc_id)
    return blocks, scanned, 0, 0


def run(settings: Settings | None = None, subset: int | None = None) -> IngestStats:
    settings = settings or get_settings()
    corpus_root = settings.corpus_root
    documents = build_logical_documents(corpus_root)[:subset]

    stats = IngestStats()
    doc_rows: list[dict] = []
    block_rows: list[dict] = []

    for index, document in enumerate(documents, start=1):
        try:
            blocks, scanned, matched, declared = ingest_document(document, corpus_root)
        except Exception as exc:  # noqa: BLE001 - dead-letter, never halt the run
            log.warning("failed %s: %s", document.canonical_path, exc)
            stats.dead_letter.append(
                {"path": document.canonical_path, "error": f"{type(exc).__name__}: {exc}"}
            )
            continue

        if declared:
            stats.outline_agreement.append((document.doc_id, matched, declared))
        if is_scan(document.canonical_path) or scanned:
            stats.scanned_pages += len(scanned)
            if scanned:
                stats.documents_needing_ocr.append(document.doc_id)

        stats.documents += 1
        stats.blocks += len(blocks)
        stats.tables += sum(1 for b in blocks if b.block_type == "table")
        stats.headings += sum(1 for b in blocks if b.block_type == "heading")

        doc_rows.append(
            {
                **asdict(document),
                "page_count": (
                    pdf_adapter.page_count(corpus_root / document.canonical_path)
                    if document.canonical_format == "pdf"
                    else 1
                ),
                "block_count": len(blocks),
                "scanned_pages": scanned,
                "ingest_status": "ok" if blocks else "partial",
                "ingested_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        block_rows.extend(b.model_dump() for b in blocks)

        if index % 40 == 0 or index == len(documents):
            print(f"  {index}/{len(documents)} documents", flush=True)

    _write(settings, "documents.jsonl", doc_rows)
    _write(settings, "blocks.jsonl", block_rows)
    if stats.dead_letter:
        _write(settings, "documents.deadletter.jsonl", stats.dead_letter)
    return stats


def _write(settings: Settings, name: str, rows: list[dict]) -> Path:
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    target = settings.index_dir / name
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows),
        encoding="utf-8",
    )
    tmp.replace(target)
    return target


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", type=int, help="ingest only the first N documents")
    args = parser.parse_args()

    settings = get_settings()
    stats = run(settings, subset=args.subset)

    print(f"\ndocuments      : {stats.documents}")
    print(f"blocks         : {stats.blocks}")
    print(f"  headings     : {stats.headings}")
    print(f"  tables       : {stats.tables}")
    print(f"scanned pages  : {stats.scanned_pages}")
    print(f"needing OCR    : {len(stats.documents_needing_ocr)} documents")
    if stats.outline_agreement:
        print(
            f"PDF/DOCX outline agreement: {stats.agreement_rate():.1%} "
            f"across {len(stats.outline_agreement)} paired documents"
        )
    print(f"dead-letter    : {len(stats.dead_letter)}")
    for entry in stats.dead_letter[:10]:
        print(f"  DEAD {entry['path']}: {entry['error'][:110]}")
    print(f"\nwrote {settings.index_dir / 'documents.jsonl'} and blocks.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
