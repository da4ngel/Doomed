"""Tests for format-twin pairing.

The corpus-wide tests are the ones that matter. Pairing decides what counts as an
independent source, and A4 breaks equal-tier conflicts by counting independent sources -
so a mistake here does not look like a bug, it looks like a confident wrong answer with
two real citations attached.
"""

from __future__ import annotations

import pytest

from src.core.config import CORPUS_ROOT
from src.ingestion.pairing import (
    build_logical_documents,
    document_id,
    is_scan,
    pairing_summary,
)


def test_document_id_collapses_format_twins() -> None:
    assert document_id("chronicles/vol_i.pdf") == document_id("chronicles/vol_i.docx")


def test_document_id_ignores_the_scan_marker() -> None:
    """`x.scan.pdf` and `x.pdf` are the same document in two conditions."""
    assert document_id("ephemera/letter_x.scan.pdf") == document_id("ephemera/letter_x.pdf")


def test_is_scan_matches_the_corpus_convention() -> None:
    assert is_scan("ephemera/ballad_x.scan.pdf")
    assert not is_scan("ephemera/ballad_x.pdf")


@pytest.fixture(scope="module")
def documents():
    if not CORPUS_ROOT.exists():
        pytest.skip("corpus not present")
    return build_logical_documents(CORPUS_ROOT)


def test_every_non_image_corpus_file_is_accounted_for(documents) -> None:
    """339 corpus files - 85 images = 254 files, none silently dropped."""
    assert pairing_summary(documents)["source_files"] == 254


def test_the_four_novels_collapse_to_four_documents(documents) -> None:
    novels = [d for d in documents if d.canonical_path.startswith("chronicles/")]
    assert len(novels) == 4
    for novel in novels:
        assert novel.canonical_format == "pdf", "PDF carries the page geometry"
        assert novel.structure_donor, "the DOCX is kept as the structure donor"


def test_no_document_is_represented_twice(documents) -> None:
    """The whole point: one logical document, one doc_id, one set of chunks."""
    ids = [d.doc_id for d in documents]
    assert len(ids) == len(set(ids))

    seen: set[str] = set()
    for document in documents:
        for path in document.all_paths:
            assert path not in seen, f"{path} claimed by two documents"
            seen.add(path)


def test_a_readable_twin_beats_a_scan_as_canonical(documents) -> None:
    """Measured: 2 of the 17 scans have a twin that actually contains text.

    Preferring the PDF for its page geometry would index an empty scan and drop the
    content entirely - the similarity check between the two came out at 0.000.
    """
    by_id = {d.doc_id: d for d in documents}

    rescued = by_id["field_report_concerning_cerys_sablewood_the_ashen"]
    assert rescued.canonical_path.endswith(".docx")
    assert any(is_scan(p) for p in rescued.alias_paths)

    rescued = by_id["interrogation_record_concerning_hesper_wrenfield"]
    assert not is_scan(rescued.canonical_path)
    assert any(is_scan(p) for p in rescued.alias_paths)


def test_only_fifteen_documents_still_need_ocr(documents) -> None:
    """Down from 17 scan files, because two had a readable twin."""
    needing_ocr = [d for d in documents if is_scan(d.canonical_path)]
    assert len(needing_ocr) == 15


def test_pairing_removes_eighteen_duplicate_files(documents) -> None:
    summary = pairing_summary(documents)
    assert summary["paired_documents"] == 17
    assert summary["files_deduplicated"] == 18
    assert summary["logical_documents"] == 236


def test_every_document_carries_tier_and_source_type(documents) -> None:
    assert all(1 <= d.authority_tier <= 5 for d in documents)
    assert all(d.tier_reason for d in documents)
    assert all(d.source_type and d.source_type != "unknown" for d in documents)


def test_tier_three_holds_exactly_the_four_novels(documents) -> None:
    """Eight files became four documents; the tier count must follow."""
    assert len([d for d in documents if d.authority_tier == 3]) == 4
