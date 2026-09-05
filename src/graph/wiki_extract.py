"""Deterministic entity and relation extraction from the 95 wiki articles.

WHY this runs before any LLM extraction: the wiki hands us the graph. Every article
carries an Infobox table and `[[wikilinks]]`, so the skeleton parses with zero LLM cost,
zero hallucination risk, and a provenance story that survives a judge asking "how do you
know this edge is real?" - the answer is "it is a table row, here is the line number".
LLM extraction is then only needed for `chronicles/` and `ephemera/`, where relations
are prose.

WHY the surface-form map is large: the infobox vocabulary is a long tail of ~100 field
labels, not the 13 clean names the original finding implied (addendum, Finding 12).
`member_of` alone appears as seven different labels. A parser keyed on canonical names
would capture a fraction of the graph and fail *quietly*, because a sparse graph looks
exactly like a working one.

Unmapped fields are counted and reported rather than dropped in silence, so field
coverage is a number we can put in the report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, get_args

from src.api.schemas import Entity, EntityType, Relation, RelationPredicate
from src.ingestion.tiers import assign_tier

VALID_PREDICATES = set(get_args(RelationPredicate))
VALID_ENTITY_TYPES = set(get_args(EntityType))

#: Infobox field label -> (predicate, direction). "inverse" means the article is the
#: OBJECT of the relation, not the subject: a character's `Mentor` field names the
#: person who mentors *them*, so the edge is mentor_of(that person, this article).
Direction = Literal["forward", "inverse"]

FIELD_MAP: dict[str, tuple[str, Direction]] = {
    # membership
    "member of": ("member_of", "forward"),
    "membership": ("member_of", "forward"),
    "affiliation": ("member_of", "forward"),
    "allegiance": ("member_of", "forward"),
    "members": ("has_member", "forward"),
    "member": ("has_member", "forward"),
    "known members": ("has_member", "forward"),
    # command
    "command": ("commands", "forward"),
    "commands": ("commands", "forward"),
    "castellan": ("commands", "inverse"),
    # relics
    "wields": ("wields", "forward"),
    "wielded relic": ("wields", "forward"),
    "wielded weapon": ("wields", "forward"),
    "weapon": ("wields", "forward"),
    "relic": ("wields", "forward"),
    "weapon or relic": ("wields", "forward"),
    "later weapon record": ("wields", "forward"),
    # mentorship
    "mentor of": ("mentor_of", "forward"),
    "mentorship": ("mentor_of", "forward"),
    "mentor": ("mentor_of", "inverse"),
    # rule
    "ruled by": ("ruled_by", "forward"),
    "ruler": ("ruled_by", "forward"),
    "ruling power": ("ruled_by", "forward"),
    # place
    "housed in": ("housed_at", "forward"),
    "place of housing": ("housed_at", "forward"),
    "seat": ("located_in", "forward"),
    "region": ("located_in", "forward"),
    "location": ("located_in", "forward"),
    "core location": ("located_in", "forward"),
    "major setting": ("located_in", "forward"),
    "forged at": ("located_in", "forward"),
    "place of forging": ("located_in", "forward"),
    "place of service": ("located_in", "forward"),
    "place of Service": ("located_in", "forward"),
    "serves at": ("located_in", "forward"),
    "service": ("located_in", "forward"),
    "lair": ("lair_of", "forward"),
    # conflict. `Victor` sits on the EVENT's article and names the winning party, so
    # the edge runs from that party to the event - inverse, not forward. Getting this
    # backwards silently breaks every "who won X" question while the graph still looks
    # populated, which is how 1b_006 was found failing.
    "victor": ("won", "inverse"),
    "victor of": ("won", "forward"),
    "belligerent": ("fought_in", "forward"),
    "belligerent in": ("fought_in", "forward"),
    "belligerencies": ("fought_in", "forward"),
    "conflict": ("fought_in", "forward"),
    "military involvement": ("fought_in", "forward"),
    "military action": ("fought_in", "forward"),
    "military record": ("fought_in", "forward"),
    "military service": ("fought_in", "forward"),
    "major fighting": ("fought_in", "forward"),
    "notable fighter": ("fought_in", "inverse"),
    "known participant": ("fought_in", "inverse"),
    # dates and secrets
    "born": ("born_in", "forward"),
    "secret": ("secret", "forward"),
    "secret truth": ("secret", "forward"),
    "concealed truth": ("secret", "forward"),
}

#: Fields that are descriptive prose, not relations. Listed explicitly so they are
#: *known* to be excluded rather than silently unmapped.
DESCRIPTIVE_FIELDS = frozenset(
    {
        "name",
        "role",
        "demeanor",
        "appearance",
        "status",
        "founded",
        "type",
        "era",
        "garrison strength",
        "artifact class",
        "attunement cost",
        "threat rating",
        "habit",
        "classification",
        "visual identity",
        "doctrine",
        "outcome",
        "began",
        "ended",
        "casualties",
        "casualty figure",
        "physical traits",
        "physical description",
        "organization type",
        "organization kind",
        "organizational kind",
        "holding classification",
        "primary function",
        "nature",
        "danger",
        "position",
        "personnel",
        "forged",
        "forging date",
        "died",
        "unleashed in",
        "devastated",
        "devastated sites",
        "major devastation",
        "waged at",
        "attack character",
        "creature",
        "character",
        "historical association",
        "related region and year",
        "related location and year",
        "rival",
        "rivals",
        "rival of",
        "serving figure",
        "serves at emberdeep",
        "serving at crookvale",
        "serves at greyfell citadel",
        "serves at the fortress",
        "personnel serving at hollowreach",
    }
)

#: `atmo_<style>_<category>_<name>.png` - the category token types the article.
IMAGE_CATEGORY_TO_TYPE: dict[str, EntityType] = {
    "character": "Character",
    "faction": "Faction",
    "artifact": "Artifact",
    "location": "Location",
    "creature": "Component",  # bestiary entries; no Creature member in the frozen enum
    "painting": "Event",
}

HEADING_TYPE_TO_TYPE: dict[str, EntityType] = {
    "character": "Character",
    "faction": "Faction",
    "artifact": "Artifact",
    "location": "Location",
    "creature": "Component",
    "conflict": "Event",
}

#: Infobox fields that betray the entity type when nothing else does.
TYPE_SIGNATURE: list[tuple[frozenset[str], EntityType]] = [
    (frozenset({"garrison strength", "founded", "ruled by", "region"}), "Location"),
    (frozenset({"born", "mentor", "mentor of", "role"}), "Character"),
    (frozenset({"attunement cost", "forged at", "artifact class", "forged"}), "Artifact"),
    (frozenset({"doctrine", "seat", "members", "organization kind"}), "Faction"),
    (frozenset({"victor", "casualties", "began", "ended", "waged at"}), "Event"),
    (frozenset({"threat rating", "lair", "habit"}), "Component"),
]

_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_HEADING_TYPE = re.compile(r"^(.*?)\s*\(([a-z ]+)\)$")
_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)
_SINCE = re.compile(r"\s+since\s+(\d+\s*[A-Z]{2})\s*$", re.IGNORECASE)

#: Some values carry the predicate in the cell rather than the field label, e.g.
#: `Outcome | Victor of The Accord of Mournthrone`.
VALUE_PREFIX_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^victor of\s+(.+)$", re.IGNORECASE), "won"),
    (re.compile(r"^housed (?:in|at)\s+(.+)$", re.IGNORECASE), "housed_at"),
]

#: High-precision prose patterns, used only for the 6 articles with no Infobox and for
#: facts an infobox omits. Each requires a `[[wikilink]]` as the object, so it cannot
#: invent an entity - it can only connect two names the corpus already wrote down.
PROSE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bis housed (?:in|at)\s+\[\[([^\]]+)\]\]", re.IGNORECASE), "housed_at"),
    (re.compile(r"\bwas forged at\s+\[\[([^\]]+)\]\]", re.IGNORECASE), "located_in"),
    (re.compile(r"\bis ruled by\s+\[\[([^\]]+)\]\]", re.IGNORECASE), "ruled_by"),
    (re.compile(r"\blair (?:is|lies) (?:in|at)\s+\[\[([^\]]+)\]\]", re.IGNORECASE), "lair_of"),
    (re.compile(r"\bis a member of\s+\[\[([^\]]+)\]\]", re.IGNORECASE), "member_of"),
    (re.compile(r"\bis seated at\s+\[\[([^\]]+)\]\]", re.IGNORECASE), "located_in"),
]


def _clean(value: str) -> str:
    """Strip wikilink brackets and bold markers from a cell value."""
    value = _WIKILINK.sub(r"\1", value)
    return value.replace("**", "").replace("*", "").strip()


def entity_id(name: str) -> str:
    """Stable slug. Canonicalisation of near-duplicates happens later, in D3."""
    slug = re.sub(r"[^a-z0-9]+", "_", _clean(name).lower()).strip("_")
    return f"ent_{slug}"


@dataclass
class WikiArticle:
    path: str
    title: str
    entity_type: EntityType
    infobox: list[tuple[str, str]] = field(default_factory=list)
    wikilinks: list[str] = field(default_factory=list)
    image: str | None = None
    image_alt: str | None = None


def _infer_type(
    title: str, heading_type: str | None, image: str | None, fields: set[str]
) -> EntityType:
    """Layered inference: heading suffix, then image category, then infobox signature.

    No single signal covers the corpus - only 26 of 95 headings carry a `(type)` suffix
    and only 55 articles have an image - so the layers matter.
    """
    if heading_type and heading_type in HEADING_TYPE_TO_TYPE:
        return HEADING_TYPE_TO_TYPE[heading_type]

    if image:
        parts = Path(image).stem.split("_")
        if len(parts) >= 3 and parts[0] == "atmo":
            mapped = IMAGE_CATEGORY_TO_TYPE.get(parts[2])
            if mapped:
                return mapped

    best: tuple[int, EntityType] = (0, "Title")
    for signature, entity_type in TYPE_SIGNATURE:
        overlap = len(signature & fields)
        if overlap > best[0]:
            best = (overlap, entity_type)
    return best[1]


def parse_article(rel_path: str, text: str) -> WikiArticle:
    """Parse one wiki markdown file into its structured parts."""
    heading_match = _HEADING.search(text)
    raw_title = _clean(heading_match.group(1)) if heading_match else Path(rel_path).stem
    heading_type = None
    typed = _HEADING_TYPE.match(raw_title)
    if typed:
        raw_title, heading_type = typed.group(1).strip(), typed.group(2).strip().lower()

    image_match = _IMAGE.search(text)
    image = image_match.group(2) if image_match else None
    image_alt = image_match.group(1) if image_match else None

    infobox: list[tuple[str, str]] = []
    section = text.split("## Infobox", 1)
    if len(section) == 2:
        body = section[1].split("\n## ", 1)[0]
        for label, value in _TABLE_ROW.findall(body):
            key = label.strip().lower()
            if key in {"field", "value"} or set(label.strip()) <= {"-", ":"}:
                continue
            infobox.append((label.strip(), value.strip()))

    return WikiArticle(
        path=rel_path,
        title=raw_title,
        entity_type=_infer_type(raw_title, heading_type, image, {k.lower() for k, _ in infobox}),
        infobox=infobox,
        wikilinks=[_clean(m) for m in _WIKILINK.findall(text)],
        image=image,
        image_alt=image_alt,
    )


def _split_values(value: str) -> list[str]:
    """Multi-valued cells use `;`. `Members | A; B; C` is three edges, not one."""
    return [part.strip() for part in value.split(";") if part.strip()]


@dataclass
class ExtractionReport:
    entities: dict[str, Entity] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)
    unmapped_fields: dict[str, int] = field(default_factory=dict)
    articles: int = 0
    articles_without_infobox: int = 0

    def field_coverage(self) -> float:
        """Share of relational infobox rows that produced an edge. Reported, not assumed."""
        mapped = len(self.relations)
        total = mapped + sum(self.unmapped_fields.values())
        return mapped / total if total else 0.0


def extract(articles: dict[str, str]) -> ExtractionReport:
    """Build the graph skeleton from `{relative_path: markdown_text}`.

    Two passes on purpose. Every article-backed entity is registered with its real type
    first, so that an entity merely *referenced* by an alphabetically earlier article
    does not get frozen as an untyped placeholder before its own article is read.
    """
    report = ExtractionReport()

    parsed = [(path, parse_article(path, text)) for path, text in sorted(articles.items())]

    # Pass 1 - article-backed entities, which are the only ones with a known type.
    for rel_path, article in parsed:
        report.articles += 1
        if not article.infobox:
            report.articles_without_infobox += 1
        eid = entity_id(article.title)
        report.entities[eid] = Entity(
            entity_id=eid,
            canonical_name=article.title,
            type=article.entity_type,
            doc_ids=[rel_path],
        )

    # Pass 2 - relations, plus placeholders for names that have no article of their own.
    for rel_path, article in parsed:
        tier, _ = assign_tier(rel_path)
        subject = entity_id(article.title)

        def add(
            predicate: str,
            other: str,
            evidence: str,
            direction: Direction = "forward",
            qualifier: str | None = None,
            subject: str = subject,
            tier: int = tier,
            rel_path: str = rel_path,
        ) -> None:
            name = _clean(other)
            if not name:
                return
            obj = entity_id(name)
            report.entities.setdefault(
                obj, Entity(entity_id=obj, canonical_name=name, type="Title", doc_ids=[rel_path])
            )
            a, b = (subject, obj) if direction == "forward" else (obj, subject)
            relation = Relation(
                subject_id=a,
                predicate=predicate,  # type: ignore[arg-type]
                object_id=b,
                evidence_chunk_id=evidence,
                authority_tier=tier,
                confidence=1.0,
                qualifier=qualifier,
            )
            if relation not in report.relations:
                report.relations.append(relation)

        for label, raw_value in article.infobox:
            key = label.lower()

            # A value that carries its own predicate wins over the field label, because
            # `Outcome | Victor of X` is a `won` edge however the column is named.
            matched_by_value = False
            for pattern, predicate in VALUE_PREFIX_MAP:
                match = pattern.match(_clean(raw_value))
                if match:
                    add(predicate, match.group(1), f"{rel_path}#infobox:{label}")
                    matched_by_value = True
                    break
            if matched_by_value:
                continue

            if key in DESCRIPTIVE_FIELDS:
                continue
            mapping = FIELD_MAP.get(key)
            if mapping is None:
                report.unmapped_fields[label] = report.unmapped_fields.get(label, 0) + 1
                continue

            predicate, direction = mapping
            for item in _split_values(raw_value):
                qualifier = None
                since = _SINCE.search(item)
                if since:
                    qualifier = f"since {since.group(1)}"
                    item = item[: since.start()].strip()

                name = _clean(item)
                if not name:
                    continue

                obj = entity_id(name)
                report.entities.setdefault(
                    obj,
                    Entity(entity_id=obj, canonical_name=name, type="Title", doc_ids=[rel_path]),
                )

                a, b = (subject, obj) if direction == "forward" else (obj, subject)
                report.relations.append(
                    Relation(
                        subject_id=a,
                        predicate=predicate,  # type: ignore[arg-type]
                        object_id=b,
                        evidence_chunk_id=f"{rel_path}#infobox:{label}",
                        authority_tier=tier,
                        confidence=1.0,
                        qualifier=qualifier,
                    )
                )
                # A relic held "since 341 AS" is also a bore_since edge, which is what
                # 1b_003 walks: person -bore_since-> relic -housed_at-> location.
                if qualifier and predicate == "wields":
                    report.relations.append(
                        Relation(
                            subject_id=a,
                            predicate="bore_since",
                            object_id=b,
                            evidence_chunk_id=f"{rel_path}#infobox:{label}",
                            authority_tier=tier,
                            confidence=1.0,
                            qualifier=qualifier,
                        )
                    )

        # Prose fallback. Six articles carry no Infobox at all, and others state in
        # prose what the table omits - the Cinder-Wrought Aegis is "housed in
        # [[Gloamreach]]" only in its text, which is hop 2 of 1b_003.
        text = articles[rel_path]
        for pattern, predicate in PROSE_PATTERNS:
            for target in pattern.findall(text):
                add(predicate, target, f"{rel_path}#prose")

    return report


def load_corpus_articles(wiki_dir: Path) -> dict[str, str]:
    return {
        f"wiki/{path.name}": path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(wiki_dir.glob("*.md"))
    }
