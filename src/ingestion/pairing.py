"""Collapse format twins into one logical document.

WHY this exists: the four novels and three codexes each ship as BOTH `.pdf` and `.docx`
with the same content — measured, not assumed: every novel has *identical* extracted
character counts in the two formats.

Indexing both is not merely wasteful. `A4 Evidence Merger` resolves equal-tier conflicts
by counting independent corroborating sources, so the same sentence appearing under two
`doc_id`s would make a single source look corroborated. That turns "unresolved, here are
both sides" into a confident, wrong resolution with two real citations attached — the
worst failure mode this system has.

WHY the PDF wins: it alone carries page numbers and bounding boxes, which the citation
page-crop and every `Citation.bbox` depend on. The DOCX is kept as a *structure donor* —
its heading styles and real table objects are cleaner than anything recoverable from a
PDF — and recorded as an alias so provenance stays honest.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from src.ingestion.tiers import assign_tier, is_corpus_file, normalise, source_type

#: Extensions we ingest, in descending order of preference as the canonical format.
#: PDF first because it is the only one with page geometry.
CANONICAL_PREFERENCE = ("pdf", "docx", "md", "txt")


def is_scan(rel_path: str) -> bool:
    """`*.scan.pdf` - the corpus convention for a page image with no text layer."""
    return normalise(rel_path).endswith(".scan.pdf")

FORMAT_BY_SUFFIX = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "md",
    ".txt": "txt",
    ".png": "png",
}


@dataclass
class LogicalDocument:
    """One document, however many files represent it."""

    doc_id: str
    canonical_path: str
    canonical_format: str
    alias_paths: list[str] = field(default_factory=list)
    authority_tier: int = 4
    tier_reason: str = ""
    source_type: str = ""
    title: str = ""

    @property
    def all_paths(self) -> list[str]:
        return [self.canonical_path, *self.alias_paths]

    @property
    def structure_donor(self) -> str | None:
        """A paired DOCX, whose heading styles beat PDF font-size clustering."""
        for path in self.alias_paths:
            if path.lower().endswith(".docx"):
                return path
        return None


def document_id(rel_path: str) -> str:
    """Stable id from the path stem, so format twins collapse onto the same id."""
    stem = Path(normalise(rel_path)).stem
    # `letter_x.scan.pdf` -> stem `letter_x.scan`; the scan marker is not identity.
    if stem.endswith(".scan"):
        stem = stem[: -len(".scan")]
    return stem.replace(" ", "_")


def title_from(rel_path: str) -> str:
    return Path(rel_path).stem.replace(".scan", "").replace("_", " ").strip().title()


def _pair_key(rel_path: str) -> tuple[str, str]:
    """Group by (directory, document id). Same folder is required — two files sharing a
    stem in different directories are different documents, not twins."""
    path = normalise(rel_path)
    return (str(Path(path).parent), document_id(path))


def build_logical_documents(corpus_root: Path) -> list[LogicalDocument]:
    """Walk the corpus and collapse format twins. Images are excluded - they are their
    own pipeline (`src/ingestion/images.py`) and already deduplicated by content hash."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)

    for path in sorted(corpus_root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(corpus_root)).replace("\\", "/")
        if not is_corpus_file(rel):
            continue
        fmt = FORMAT_BY_SUFFIX.get(path.suffix.lower())
        if fmt is None or fmt == "png":
            continue
        groups[_pair_key(rel)].append(rel)

    documents: list[LogicalDocument] = []
    for (_, doc_id), paths in sorted(groups.items()):
        # A scan sorts last however good its format is. `field_report_...scan.pdf` and
        # `...docx` are the same document: the scan has page geometry but no text layer,
        # the DOCX has the text. Preferring the PDF purely for its geometry would index
        # an empty document and silently drop the content - measured on 2 of the 17 scans.
        ordered = sorted(
            paths,
            key=lambda p: (
                is_scan(p),
                CANONICAL_PREFERENCE.index(FORMAT_BY_SUFFIX[Path(p).suffix.lower()]),
                p,
            ),
        )
        canonical = ordered[0]
        tier, reason = assign_tier(canonical)
        documents.append(
            LogicalDocument(
                doc_id=doc_id,
                canonical_path=canonical,
                canonical_format=FORMAT_BY_SUFFIX[Path(canonical).suffix.lower()],
                alias_paths=ordered[1:],
                authority_tier=tier,
                tier_reason=reason,
                source_type=source_type(canonical),
                title=title_from(canonical),
            )
        )
    return documents


def pairing_summary(documents: list[LogicalDocument]) -> dict[str, int]:
    """Numbers for the report: how much duplication the pairing removed."""
    paired = [d for d in documents if d.alias_paths]
    return {
        "logical_documents": len(documents),
        "source_files": sum(len(d.all_paths) for d in documents),
        "paired_documents": len(paired),
        "files_deduplicated": sum(len(d.alias_paths) for d in paired),
    }
