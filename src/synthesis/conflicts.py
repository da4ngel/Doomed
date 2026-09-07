"""A4 conflict detection — cluster assertions, resolve by authority tier, or refuse.

WHY this is load-bearing rather than a differentiator bolted on: both 1C dev questions
are contradiction questions, and so is at least one 1A question. `1a_004` asks the
Thrice-Bound Edge's attunement cost; the tier-1 plate says **94** while the tier-2 wiki
asserts "no attunement cost" six times *and outranks the plate on dense similarity*.
Without tier resolution that question returns a fluent, well-cited, wrong answer.

WHY extraction is pattern-based and not an LLM call: the assertions we need are numeric
attributes stated in a small number of regular forms. Patterns are deterministic, free
and auditable, and a conflict this system reports must be one a human can verify by
opening the two documents.

WHY attribution is strict — the hard-won part. A first version attributed each attribute
to the longest entity name anywhere in the chunk, and it invented conflicts wholesale:
"Brannoc Ironmere the Red-Handed founding year" (a person has none), "Gauntlet of
Sorrowfell founding year" scraped from an unrelated sentence in a 450-token novel chunk.
It also missed both real conflicts. An invented disagreement is worse than a missed one,
because it manufactures doubt about facts nobody disputes. So attribution now requires
BOTH:

1. **Proximity** — the entity is named in the same sentence as the value, or the chunk is
   a structured record whose subject is its section heading.
2. **Type agreement** — a Location has a founding year, an Artifact has a forging year
   and an attunement cost, a Component has a threat rating. A Character has none of them.

WHY equal tiers refuse to resolve: surfacing the disagreement is the feature. A
confidently mis-resolved conflict is a fabrication with two real citations attached.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from src.api.schemas import Chunk, Conflict

#: attribute -> (patterns, entity types that can legitimately have it).
#: The type gate is what stops a novel chunk assigning a founding year to a swordsman.
ATTRIBUTE_SPECS: dict[str, tuple[list[re.Pattern[str]], frozenset[str]]] = {
    "founding year": (
        [
            re.compile(r"\|\s*Founded\s*\|\s*([^|\n]+?)\s*\|", re.IGNORECASE),
            re.compile(r"(?:'s|s')\s+founded\s+is\s+\*{0,2}(\d{1,4}\s*AS)", re.IGNORECASE),
            re.compile(r"\bfounded\s+in\s+\*{0,2}(\d{1,4}\s*AS)", re.IGNORECASE),
        ],
        frozenset({"Location"}),
    ),
    "forging year": (
        [
            re.compile(r"\|\s*Forged\s*\|\s*([^|\n]*?\d{1,4}\s*AS[^|\n]*?)\s*\|", re.IGNORECASE),
            re.compile(r"\bForged:\s*\*{0,2}(\d{1,4}\s*AS)", re.IGNORECASE),
            re.compile(r"(?:'s|s')\s+forged\s+is\s+\*{0,2}(\d{1,4}\s*AS)", re.IGNORECASE),
            re.compile(r"\bforged\s+year\s+is\s+\*{0,2}(\d{1,4}\s*AS)", re.IGNORECASE),
            re.compile(r"\bforged\s+in\s+\*{0,2}(\d{1,4}\s*AS)", re.IGNORECASE),
        ],
        frozenset({"Artifact"}),
    ),
    "attunement cost": (
        [
            re.compile(r"\|\s*Attunement cost\s*\|\s*([^|\n]+?)\s*\|", re.IGNORECASE),
            re.compile(r"\bAttunement Cost:\s*\*{0,2}([^\n*.]+)", re.IGNORECASE),
            re.compile(r"\b(no\s+attunement\s+cost)\b", re.IGNORECASE),
        ],
        frozenset({"Artifact"}),
    ),
    "garrison strength": (
        [
            re.compile(r"\|\s*Garrison strength\s*\|\s*([^|\n]+?)\s*\|", re.IGNORECASE),
            re.compile(
                r"garrison\s+strength\s+(?:of\s+|is\s+|was\s+)?\*{0,2}(\d[\d,]*)",
                re.IGNORECASE,
            ),
        ],
        frozenset({"Location"}),
    ),
    "threat rating": (
        [re.compile(r"\|\s*Threat rating\s*\|\s*([^|\n]+?)\s*\|", re.IGNORECASE)],
        frozenset({"Component"}),
    ),
}

_SENTENCE = re.compile(r"[^.!?\n]+[.!?\n]?")


def normalise_value(raw: str) -> str:
    """Compare values on meaning, not formatting: "1,114" and "1114" are one value."""
    value = raw.strip().strip("*_ ").replace(",", "")
    value = re.sub(r"\s+", " ", value)
    if re.fullmatch(r"\d+\s*AS", value, re.IGNORECASE):
        return re.sub(r"\s*AS", " AS", value.upper()).strip()
    # "4672 troops" and "4672" are one claim. Reporting the unit as a disagreement is
    # reporting formatting, which is exactly what this layer must not do.
    bare = re.fullmatch(r"(\d+)\s*[a-z-]+", value, re.IGNORECASE)
    if bare:
        return bare.group(1)
    return value.lower()


def is_absence_claim(value: str) -> bool:
    """ "None recorded" is an assertion, not a missing value.

    The Thrice-Bound Edge's article says "no attunement cost" six times. That positively
    contradicts the plate's 94, and treating it as absent data would hide the most
    important conflict in the corpus.
    """
    return normalise_value(value) in {
        "none recorded",
        "none",
        "no attunement cost",
        "not recorded",
        "unrecorded",
        "",
    }


@dataclass
class Assertion:
    entity: str
    attribute: str
    value: str
    chunk_id: str
    doc_id: str
    authority_tier: int
    excerpt: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.entity.lower(), self.attribute)


def _subject_of(chunk: Chunk, typed: dict[str, str]) -> str | None:
    """The entity a structured record is *about*, from its section heading.

    A wiki article's chunks carry the article title as `section_path[0]`, and an infobox
    row is a statement about that subject. This is far more reliable than scanning the
    chunk for names, which is what produced the invented conflicts.
    """
    for heading in chunk.section_path[:2]:
        cleaned = heading.strip()
        if cleaned in typed:
            return cleaned
    return None


def _nearest_preceding(
    text: str, position: int, typed: dict[str, str], allowed: frozenset[str], window: int = 400
) -> str | None:
    """The type-appropriate entity named most recently before `position`.

    The codex gazetteer is a flat run of records - "Blackford ... Founded 159 AS ...
    Cindermere Hold ... Founded 246 AS" - so one chunk holds several entries and the
    section heading names only the first. Taking that heading attributed every value in
    the chunk to Blackford and manufactured a conflict between two different places.
    Reading backwards from the value finds the record it actually belongs to.
    """
    haystack = text[max(0, position - window) : position].lower()
    best: tuple[int, str] | None = None
    for name, kind in typed.items():
        if kind not in allowed:
            continue
        at = haystack.rfind(name.lower())
        if at == -1:
            continue
        # Nearest wins; on a tie the longer name wins ("Greyfell Citadel" over "Greyfell").
        if best is None or (at, len(name)) > (best[0], len(best[1])):
            best = (at, name)
    return best[1] if best else None


def _entity_in(sentence: str, typed: dict[str, str], allowed: frozenset[str]) -> str | None:
    """The longest type-appropriate entity named in this sentence, if any."""
    lowered = sentence.lower()
    candidates = [
        name for name, kind in typed.items() if kind in allowed and name.lower() in lowered
    ]
    return max(candidates, key=len) if candidates else None


def extract_assertions(chunk: Chunk, typed_entities: dict[str, str]) -> list[Assertion]:
    """Pull attribute claims from one chunk, strictly attributed.

    `typed_entities` maps canonical name -> entity type, from the graph. Both the
    proximity rule and the type gate depend on it.
    """
    text = chunk.text
    subject = _subject_of(chunk, typed_entities)
    found: list[Assertion] = []
    claimed: set[tuple[str, str, str]] = set()

    for attribute, (patterns, allowed) in ATTRIBUTE_SPECS.items():
        for pattern in patterns:
            for match in pattern.finditer(text):
                raw = match.group(1) if match.groups() else match.group(0)
                value = normalise_value(raw)
                if not value or len(value) > 60:
                    continue
                if is_absence_claim(value):
                    value = "none recorded"

                # Which entity is this about? A structured record's subject wins, but
                # only if its type can actually hold the attribute.
                entity = _nearest_preceding(text, match.start(), typed_entities, allowed)
                if entity is None and subject and typed_entities.get(subject) in allowed:
                    entity = subject
                if entity is None:
                    continue

                if (entity, attribute, value) in claimed:
                    continue
                claimed.add((entity, attribute, value))

                start = max(0, match.start() - 70)
                found.append(
                    Assertion(
                        entity=entity,
                        attribute=attribute,
                        value=value,
                        chunk_id=chunk.chunk_id,
                        doc_id=chunk.doc_id,
                        authority_tier=chunk.authority_tier,
                        excerpt=" ".join(text[start : match.end() + 50].split()),
                    )
                )
    return found


@dataclass
class MergeReport:
    conflicts: list[Conflict] = field(default_factory=list)
    reliability_notes: list[str] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    #: Two readings of the SAME asset that disagree. Not a conflict between sources -
    #: one picture, two extractors - so it is kept for audit, never rendered as a
    #: disagreement between archive documents.
    extraction_disagreements: list[str] = field(default_factory=list)


def _resolve(winners: list[Assertion], losers: list[Assertion]) -> tuple[str, str]:
    """Decide a conflict and say why in one sentence."""
    top = winners[0].authority_tier
    other = losers[0].authority_tier
    corroborating = {a.doc_id for a in winners}

    if top == other:
        return (
            "unresolved",
            f"Both claims sit at tier {top} and neither is corroborated by an "
            "independent source, so the disagreement is surfaced rather than decided.",
        )
    if len(corroborating) > 1 and top == 1:
        return (
            "tier_1_corroborated",
            f"The tier-1 reading is corroborated by {len(corroborating)} independent "
            f"documents; the competing claim is tier {other}.",
        )
    weaker = {
        5: "Tier 5 is folkloric and attested but unreliable.",
        4: "Tier 4 is primary evidence but partial.",
        3: "Tier 3 is narrative, where a fact may be spoken by an unreliable character.",
        2: "Tier 2 is encyclopaedic commentary rather than an official record.",
    }
    return (
        "higher_tier",
        f"Tier {top} outranks tier {other}. {weaker.get(other, '')}".strip(),
    )


def detect_conflicts(
    chunks: list[Chunk], typed_entities: dict[str, str], question: str = ""
) -> MergeReport:
    """Cluster assertions by (entity, attribute) and resolve disagreements by tier.

    This is the function P2's composer calls. It returns `conflicts[]` exactly as the
    frozen `Conflict` schema defines it, so rendering needs no translation.
    """
    report = MergeReport()

    seen: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        report.assertions.extend(extract_assertions(chunk, typed_entities))

    clustered: dict[tuple[str, str], list[Assertion]] = defaultdict(list)
    for assertion in report.assertions:
        clustered[assertion.key].append(assertion)

    for (_entity, attribute), group in sorted(clustered.items()):
        by_value: dict[str, list[Assertion]] = defaultdict(list)
        for assertion in group:
            by_value[assertion.value].append(assertion)
        if len(by_value) < 2:
            continue

        ranked = sorted(
            by_value.items(),
            key=lambda kv: (
                min(a.authority_tier for a in kv[1]),
                -len({a.doc_id for a in kv[1]}),
            ),
        )
        (value_a, winners), (value_b, losers) = ranked[0], ranked[1]

        # One image, two extractors, two numbers. The VLM description and the OCR text
        # of a plate live in the same img: chunk, so a misread digit used to surface as
        # a tier-1 archive source contradicting itself - with the SAME png named on both
        # sides. That is an extraction defect, not a disagreement between documents, and
        # rendering it as one invents a controversy the archive does not contain.
        #
        # Kept for audit rather than dropped: a plate whose two readers disagree is worth
        # knowing about, it is just not evidence about the world.
        same_asset = (
            {a.doc_id for a in winners} == {a.doc_id for a in losers}
            and len({a.doc_id for a in winners}) == 1
            and all(a.chunk_id.startswith("img:") for a in (*winners, *losers))
        )
        if same_asset:
            report.extraction_disagreements.append(
                f"{winners[0].entity} {attribute}: {winners[0].doc_id} reads "
                f"{value_a!r} and {value_b!r} from the same image. One of the two "
                "extractors misread it; this is not two sources disagreeing."
            )
            continue

        resolution, rationale = _resolve(winners, losers)

        report.conflicts.append(
            Conflict(
                attribute=f"{winners[0].entity} {attribute}",
                claim_a="none recorded" if is_absence_claim(value_a) else value_a,
                sources_a=sorted({a.doc_id for a in winners}),
                tier_a=min(a.authority_tier for a in winners),
                claim_b="none recorded" if is_absence_claim(value_b) else value_b,
                sources_b=sorted({a.doc_id for a in losers}),
                tier_b=min(a.authority_tier for a in losers),
                resolution=resolution,  # type: ignore[arg-type]
                rationale=rationale,
            )
        )

        best = min(a.authority_tier for a in winners)
        if best >= 4:
            report.reliability_notes.append(
                f"The best source for {winners[0].entity} {attribute} is tier {best} "
                "- primary but partial."
            )

    return report
