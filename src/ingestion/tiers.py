"""Authority tier assignment - directory first, filename second.

WHY directory first: the original filename-pattern rules left 87 of 340 files
unclassified (corpus findings, Finding 5). The archive's directory structure maps to
provenance almost perfectly, because that is how the corpus authors organised it. A
filename is a weaker signal than the folder a curator deliberately put the file in.

WHY this matters more than it looks: tier drives conflict resolution in agent A4. A
wrong tier table produces confidently wrong conflict outcomes, which is strictly worse
than having no conflict layer at all - an unresolved disagreement is honest, a
confidently mis-resolved one is a fabrication with a citation attached.

The tiers, per CLAUDE.md:
    1 official reference   codex data books, figure plates, canonical tables
    2 encyclopaedic        wiki articles
    3 primary narrative    the four novel volumes
    4 primary record       letters, ledgers, trial transcripts   (partial but primary)
    5 unreliable           ballads, sermons, tavern tales        (attested but unreliable)

The tier-2-vs-tier-3 ordering is a judgment call recorded in ADR-003: the wiki is a
*fan* wiki commenting on the novels, which are primary canon. We keep the wiki above
the novels anyway, because the wiki is the corpus's structured reference layer and the
novels are narrative prose - but the argument runs both ways and the report says so.
"""

from __future__ import annotations

from pathlib import PurePosixPath

#: Files that are inputs to evaluation, not archive content.
NON_CORPUS_FILES = frozenset({"sample_questions.json", "readme.txt"})

#: Prefixes within ephemera/ whose in-world author is unreliable by design. The corpus
#: README warns explicitly: "in-world authors are not always reliable."
FOLKLORIC_PREFIXES = ("ballad", "sermon")


def normalise(rel_path: str) -> str:
    """Lowercase POSIX form, so Windows and Linux agree on every rule below."""
    return rel_path.lower().replace("\\", "/").lstrip("./")


def is_corpus_file(rel_path: str) -> bool:
    """False for evaluation inputs and the corpus README."""
    return PurePosixPath(normalise(rel_path)).name not in NON_CORPUS_FILES


def assign_tier(rel_path: str) -> tuple[int, str]:
    """Return (tier, reason). The reason is logged and surfaced in citations."""
    path = normalise(rel_path)
    name = PurePosixPath(path).name

    if path.startswith(("codex/", "images/")) or "/plate_" in path or name.startswith("plate_"):
        return 1, "codex / official figure plate"
    if path.startswith("wiki/"):
        return 2, "fan-wiki article"
    if path.startswith("chronicles/"):
        return 3, "narrative novel"
    if path.startswith("ephemera/"):
        if name.startswith(FOLKLORIC_PREFIXES):
            return 5, "folkloric / homiletic - unreliable narrator"
        return 4, "in-world primary record"
    return 4, "unknown provenance - flag for review"


def source_type(rel_path: str) -> str:
    """Coarse provenance label used for payload filtering on POST /v1/search.

    Derived from the ephemera naming convention (`letter_concerning_...`,
    `ledger_concerning_...`), which is why it is cheap and deterministic.
    """
    path = normalise(rel_path)
    name = PurePosixPath(path).name

    if name.startswith("plate_"):
        return "figure_plate"
    if path.startswith("codex/"):
        return "codex"
    if path.startswith("images/"):
        return "figure_plate"
    if path.startswith("wiki/"):
        return "wiki_image" if "/images/" in path else "wiki"
    if path.startswith("chronicles/"):
        return "novel"
    if path.startswith("ephemera/"):
        # `interrogation_record_concerning_x.scan.pdf` -> `interrogation_record`
        stem = name.split("_concerning_", 1)[0]
        return stem or "ephemera"
    return "unknown"
