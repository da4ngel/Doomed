"""Context expansion — ablation rows 5 and 6.

Two different jobs that are easy to confuse, so they are separate functions with separate
ablation rows:

**Section expansion (row 5)** pulls the chunks either side of a hit. It can only ever add
chunks from documents the base retrieval already found, so it is arithmetically
**incapable of improving `coverage@k`** — a document-level metric. It improves what the
composer *sees*, not what the retriever *reaches*. Bundling it with graph expansion would
let it inherit credit for a gain it cannot produce.

**Graph expansion (row 6)** is the one that can move coverage. It walks one hop out from
the entities named in the query and pulls in the *documents of the entities it reaches* —
which is precisely the failure mode on multi-hop: a question naming an event retrieves the
event's article, while the answer needs the victor faction's article, and that article
does not contain the event name in a form either retriever scores highly.

WHY it resolves to documents rather than to `evidence_chunk_id`: a relation's evidence id
is a *source reference* into the wiki markdown (`wiki/x.md#infobox:Member of`), not an id
in the chunk index. Retrieving it directly yields an empty hit — the first version of this
module did exactly that and returned five hits with no text. The edge id remains the
citation for the hop; the document is what gets retrieved.

WHY one chunk per reached document: `coverage@k` counts documents, and the slots are
scarce. Spending a slot on a second chunk of a document already reached buys nothing,
while spending it on a first chunk of a new one may complete the answer.

WHY query entity matching is exact: the same article-insensitive rule as `entity_id()` and
nothing more. Fuzzy matching on invented proper nouns is how `greyfell_citadel` (garrison
3,695) becomes `ironfell_citadel` (1,096) — a wrong number carrying a real citation
(addendum, Finding 13).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.api.schemas import Entity
from src.graph.store import GraphStore, Hop

#: Hops to walk from an entity named in the query. One hop answers "who won X, and who
#: are they" - the shape every dev 1B question actually has. Two hops from a hub reaches
#: most of the graph and lets the cap, rather than the question, choose the evidence.
DEFAULT_HOPS = 1

#: Ceiling on chunks added by graph expansion, before the caller's budget is applied.
MAX_GRAPH_CHUNKS = 12

#: Minimum edge confidence that may spend an expansion slot. 1.0 means deterministic
#: wiki edges only.
#:
#: Measured, and it is the most counter-intuitive number in this module: adding 193
#: LLM-extracted edges (confidence 0.6) took 1B coverage@10 DOWN from 0.714 to 0.571.
#: Not because the edges are wrong - because an expansion slot EVICTS a base hit, and
#: with wiki edges alone part of the budget simply went unspent. The extracted edges
#: filled those slots with tier-3 novel chunks that displaced gold documents the base
#: retriever had already found.
#:
#: So the edges stay in the graph, where `/v1/graph/neighbors` and `/paths` use them to
#: answer and to show hop chains, and they stay out of retrieval, where their cost is
#: measured and their benefit is not. Lower this to include them and re-run the
#: ablation; the row is `6b. + graph expand (all edges)`.
MIN_EXPANSION_CONFIDENCE = 1.0

#: Chunks either side of a hit for section expansion.
SECTION_WINDOW = 1

#: Entity names shorter than this are never matched against a query. Short names appear
#: inside ordinary words and would attach an entity to almost every question.
MIN_NAME_CHARS = 4

#: Only typed entities may seed a walk. `Title` is the extractor's catch-all and holds
#: literals - years, secret text, whole infobox values like "Fought in The Purge of
#: Blackport for The Iron-Ring Cartel" - which are values, not names a question calls by.
#: They remain perfectly good *destinations*: such a node carries the doc_id of the
#: character whose infobox stated it, which is often exactly the second-hop document.
SEED_TYPES = frozenset({"Character", "Faction", "Location", "Artifact", "Event", "Component"})


@dataclass
class Expansion:
    """What expansion added, and why — so a trace can show its working."""

    chunk_ids: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    hops: list[Hop] = field(default_factory=list)
    #: chunk_id -> the reason it was added. A chunk that reached the evidence bundle
    #: without a retriever score and without an explanation is exactly the kind of thing
    #: that gets cited in an answer nobody can defend.
    reasons: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.chunk_ids)


def _normalise(text: str) -> str:
    """Lowercase, punctuation to single spaces. Matches `entity_id`'s alphabet."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def doc_slug(reference: str) -> str:
    """`wiki/the_purge_of_blackport.md` -> `the_purge_of_blackport`.

    The graph records where an entity was *read from*; the chunk index records what a
    document is *called*. For wiki articles those differ by a directory and an extension,
    and nothing else — so this is a translation, not a guess. Callers try the raw
    reference first, because image documents keep their full path as their id.
    """
    name = reference.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def entities_in_query(query: str, vocabulary: list[Entity]) -> list[Entity]:
    """Entities whose canonical name appears verbatim in the query.

    Longest name first, so "The War of Drowned Light" wins and "Drowned Light" is not
    also reported — one mention is one entity.

    Exact containment only. Correcting a misspelling is A1's job, against the published
    vocabulary, before the request is made. This function must never guess: guessing is
    what produces a confident answer about the wrong castle.
    """
    haystack = f" {_normalise(query)} "
    matches: list[Entity] = []
    claimed: list[tuple[int, int]] = []

    for candidate in sorted(vocabulary, key=lambda e: -len(e.canonical_name)):
        if candidate.type not in SEED_TYPES:
            continue
        for name in (candidate.canonical_name, *candidate.aliases):
            if len(name) < MIN_NAME_CHARS:
                continue
            needle = f" {_normalise(name)} "
            if len(needle.strip()) < MIN_NAME_CHARS or needle not in haystack:
                continue
            start = haystack.index(needle)
            span = (start, start + len(needle))
            # A longer name already covering this span wins; do not report both.
            if any(s <= span[0] and span[1] <= e for s, e in claimed):
                break
            claimed.append(span)
            matches.append(candidate)
            break
    return matches


def graph_expand(
    query: str,
    store: GraphStore,
    vocabulary: list[Entity],
    doc_chunks: dict[str, list[str]],
    hops: int = DEFAULT_HOPS,
    max_chunks: int = MAX_GRAPH_CHUNKS,
    exclude_docs: set[str] | None = None,
    min_confidence: float = MIN_EXPANSION_CONFIDENCE,
) -> Expansion:
    """Walk out from entities named in the query and retrieve the documents reached.

    Edges are taken by (confidence, authority tier), and that order is load-bearing.
    Every expansion slot EVICTS a base hit, so a candidate must be worth more than the
    hit it displaces. A deterministic wiki edge (confidence 1.0) read off an infobox row
    is; a 0.6-confidence edge read out of a novel by a model usually is not.

    Measured: sorting by tier alone, adding 193 LLM-extracted edges took 1B coverage
    DOWN from 0.714 to 0.571, because tier-3 novel documents began evicting good base
    hits. More edges is not better under a fixed budget - better edges first is.

    Self-loops are skipped. The wiki extractor produces them where an article's infobox
    names its own subject (an event page whose `Conflict` row is the event), and an edge
    from a thing to itself licenses no new document.
    """
    exclude_docs = set(exclude_docs or ())
    result = Expansion()

    seeds = entities_in_query(query, vocabulary)
    if not seeds:
        return result

    names = store.names()
    collected: list[Hop] = []
    seed_ids = {seed.entity_id for seed in seeds}

    for seed in seeds:
        result.entities.append(seed.entity_id)
        _, edges = store.neighbors(seed.entity_id, hops=hops)
        collected += [
            hop
            for hop in edges
            if hop.subject_id != hop.object_id and hop.confidence >= min_confidence
        ]

    # Sort BEFORE deduplicating. The same triple is often attested twice - once by a
    # wiki infobox row (confidence 1.0) and once by a sentence in a novel (0.6) - and
    # deduplicating first lets whichever the walk reached first win. That is how adding
    # 193 extracted edges took 1B coverage from 0.714 to 0.571: low-confidence
    # duplicates were shadowing the authoritative edges, then sorting to the back.
    collected.sort(key=lambda h: (-h.confidence, h.authority_tier))

    seen_edges: set[tuple[str, str, str]] = set()
    deduped: list[Hop] = []
    for hop in collected:
        key = (hop.subject_id, hop.predicate, hop.object_id)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        deduped.append(hop)
    collected = deduped
    reached_docs = set(exclude_docs)

    for hop in collected:
        other_id = hop.object_id if hop.subject_id in seed_ids else hop.subject_id
        neighbour = store.entity(other_id)
        if neighbour is None:
            continue
        for reference in neighbour.doc_ids:
            doc_id = reference if reference in doc_chunks else doc_slug(reference)
            if doc_id in reached_docs or doc_id not in doc_chunks:
                continue
            chunk_id = doc_chunks[doc_id][0]
            reached_docs.add(doc_id)
            result.chunk_ids.append(chunk_id)
            result.hops.append(hop)
            result.reasons[chunk_id] = (
                f"reached via {hop.as_text(names)} — evidence {hop.evidence_chunk_id}"
            )
            break
        if len(result.chunk_ids) >= max_chunks:
            break

    return result


def section_expand(
    chunk_ids: list[str],
    ordered_chunk_ids: list[str],
    metadata,
    window: int = SECTION_WINDOW,
    exclude: set[str] | None = None,
) -> Expansion:
    """Neighbouring chunks from the same document and section as each hit.

    Bounded by `section_path`: chunking never spans a section boundary, so crossing one
    here would undo that guarantee and hand the composer prose from a different subject
    under the hit's heading.

    `ordered_chunk_ids` is index build order, which is document order — the same list BM25
    is indexed against, so position arithmetic is valid without a second store.
    """
    exclude = set(exclude or ())
    position = {chunk_id: i for i, chunk_id in enumerate(ordered_chunk_ids)}
    result = Expansion()

    for chunk_id in chunk_ids:
        index = position.get(chunk_id)
        if index is None:
            continue
        origin = metadata(chunk_id)
        for offset in range(-window, window + 1):
            if offset == 0:
                continue
            neighbour_index = index + offset
            if not 0 <= neighbour_index < len(ordered_chunk_ids):
                continue
            neighbour = ordered_chunk_ids[neighbour_index]
            if neighbour in exclude or neighbour in result.reasons:
                continue
            payload = metadata(neighbour)
            if payload.get("doc_id") != origin.get("doc_id"):
                continue
            if payload.get("section_path") != origin.get("section_path"):
                continue
            result.chunk_ids.append(neighbour)
            side = "before" if offset < 0 else "after"
            result.reasons[neighbour] = f"section neighbour {side} {chunk_id}"

    return result


def build_doc_chunks(ordered_chunk_ids: list[str], metadata) -> dict[str, list[str]]:
    """doc_id -> its chunk ids, in index order.

    Built once per retriever. Graph expansion needs to go from a document to *a* chunk of
    it, which is the opposite direction from everything else in the index.
    """
    index: dict[str, list[str]] = {}
    for chunk_id in ordered_chunk_ids:
        doc_id = metadata(chunk_id).get("doc_id")
        if doc_id:
            index.setdefault(doc_id, []).append(chunk_id)
    return index
