"""Tier assignment tests, including a run over the whole real corpus.

The corpus-wide test is the one that matters. The previous filename-pattern rules left
87 files unclassified and nobody noticed until the profile was read; asserting zero
unclassified files against the actual archive is what stops that recurring.
"""

from __future__ import annotations

import pytest

from src.core.config import CORPUS_ROOT
from src.ingestion.tiers import assign_tier, is_corpus_file, normalise, source_type


@pytest.mark.parametrize(
    ("path", "tier"),
    [
        ("codex/the_annals_of_the_ashen_era.pdf", 1),
        ("codex/images/plate_01_location_emberdeep.png", 1),
        ("images/plate_09_location_greyfell_citadel.png", 1),
        ("wiki/aldous_wrenfield_the_last_warden.md", 2),
        ("wiki/images/atmo_heraldry_faction_house_morvain.png", 2),
        ("chronicles/the_ashen_chronicles_volume_ii_the_long_reprisal.pdf", 3),
        ("ephemera/letter_concerning_the_accord_of_mournthrone.scan.pdf", 4),
        ("ephemera/interrogation_record_concerning_greyfell_citadel.scan.pdf", 4),
        ("ephemera/ballad_concerning_crookgate_keep.scan.pdf", 5),
        ("ephemera/sermon_concerning_fenthrone.scan.pdf", 5),
    ],
)
def test_known_paths_land_in_the_right_tier(path: str, tier: int) -> None:
    assert assign_tier(path)[0] == tier


def test_windows_separators_are_handled() -> None:
    """Ingestion runs on Windows here and in CI on Linux; both must agree."""
    assert assign_tier(r"wiki\house_morvain.md")[0] == 2
    assert normalise(r"Wiki\House_Morvain.MD") == "wiki/house_morvain.md"


def test_every_tier_carries_a_human_readable_reason() -> None:
    for path in ("codex/x.pdf", "wiki/x.md", "chronicles/x.pdf", "ephemera/ballad_x.txt"):
        tier, reason = assign_tier(path)
        assert 1 <= tier <= 5
        assert reason and not reason.endswith(" ")


def test_ballads_and_sermons_outrank_nothing() -> None:
    """Tier 5 is 'attested but unreliable' - it must never beat a primary record."""
    assert (
        assign_tier("ephemera/ballad_concerning_x.pdf")[0]
        > assign_tier("ephemera/ledger_concerning_x.pdf")[0]
    )


def test_evaluation_inputs_are_not_corpus_content() -> None:
    assert not is_corpus_file("sample_questions.json")
    assert not is_corpus_file("README.txt")
    assert is_corpus_file("wiki/emberdeep.md")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("images/plate_01_location_emberdeep.png", "figure_plate"),
        ("codex/images/plate_01_location_emberdeep.png", "figure_plate"),
        ("codex/the_annals_of_the_ashen_era.pdf", "codex"),
        ("wiki/emberdeep.md", "wiki"),
        ("wiki/images/atmo_portrait_character_x.png", "wiki_image"),
        ("chronicles/volume_i.pdf", "novel"),
        ("ephemera/ballad_concerning_crookgate_keep.scan.pdf", "ballad"),
        ("ephemera/interrogation_record_concerning_ashreach.scan.pdf", "interrogation_record"),
    ],
)
def test_source_type_is_derived_from_the_naming_convention(path: str, expected: str) -> None:
    assert source_type(path) == expected


@pytest.mark.skipif(not CORPUS_ROOT.exists(), reason="corpus not present")
def test_no_file_in_the_real_corpus_is_unclassified() -> None:
    """Finding 5: the filename rules left 87 files unclassified. This must be zero."""
    unclassified = [
        str(p.relative_to(CORPUS_ROOT))
        for p in CORPUS_ROOT.rglob("*")
        if p.is_file()
        and is_corpus_file(str(p.relative_to(CORPUS_ROOT)))
        and assign_tier(str(p.relative_to(CORPUS_ROOT)))[1].startswith("unknown")
    ]
    assert unclassified == [], f"{len(unclassified)} unclassified: {unclassified[:5]}"


@pytest.mark.skipif(not CORPUS_ROOT.exists(), reason="corpus not present")
def test_corpus_tier_distribution_matches_the_findings() -> None:
    """Finding 5 predicts 36 / 150 / 8 / 113 / 32.

    That sums to 339, not 340: the findings counted README.txt as a document, but it
    is metadata describing the archive rather than in-world archive content, so
    ingestion skips it alongside sample_questions.json.
    """
    from collections import Counter

    counts: Counter[int] = Counter()
    for path in CORPUS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(CORPUS_ROOT))
        if is_corpus_file(rel):
            counts[assign_tier(rel)[0]] += 1

    assert sum(counts.values()) == 339, counts
    assert counts[3] == 8, "the four novels in two formats each"
    assert counts[5] == 32, "19 ballads + 13 sermons"
    # The wiki plus its images dominate; codex plus standalone plates are next.
    assert counts[2] == 150, counts
    assert counts[1] == 36, counts
    assert counts[4] == 113, counts
