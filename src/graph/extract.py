"""LLM relation extraction over `chronicles/` and `ephemera/`.

The wiki hands us a graph for free — 198 entities and 379 relations, deterministic, zero
hallucination risk (ADR-005). It also hands us a ceiling: an entity whose only stated
relationship lives in a novel or a letter has no edge, and graph expansion cannot reach
it. This module raises that ceiling for the 1,632 narrative chunks the wiki does not
cover.

**The design decision that makes this safe: extraction is closed-vocabulary in both
directions.**

- **Endpoints** must be entities the wiki already knows, and must already be *named in
  the passage*. The model is not asked who exists; it is shown the entities present and
  asked how they relate. It cannot invent a character, and it cannot connect two things
  that do not appear together in the text.
- **Predicates** must come from the frozen relation vocabulary. Anything else is dropped
  and counted.

What is left for the model is the one thing it is genuinely good at and we are not:
reading narrative prose and recognising that "Cerys had trained him since the siege"
is `mentor_of`. Every other degree of freedom is removed, because every other degree of
freedom is a way to manufacture an edge that looks sourced and is not.

Extracted edges are marked `confidence = 0.6` against the wiki's 1.0 — they are read out
of prose by a model, not off an infobox row, and a consumer choosing between two
contradictory edges should be able to tell which is which. `evidence_chunk_id` is a real,
retrievable chunk id, unlike the wiki's source references.

Corpus text enters the prompt through `src/core/evidence.py`, delimited and labelled as
data. This corpus is full of in-world orders and trial transcripts, so that is not a
formality.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from src.api.schemas import Entity, Relation, RelationPredicate
from src.core.config import get_settings
from src.core.evidence import render
from src.core.llm import LLMClient, NoProviderConfiguredError
from src.graph.store import GraphStore
from src.retrieval.expand import entities_in_query

log = logging.getLogger(__name__)

#: The frozen relation vocabulary, as a runtime set for validation.
PREDICATES: frozenset[str] = frozenset(RelationPredicate.__args__)  # type: ignore[attr-defined]

#: Read out of prose by a model rather than off an infobox row. The wiki's edges keep
#: 1.0; this gap is what lets a consumer prefer the deterministic edge when two disagree.
LLM_CONFIDENCE = 0.6

#: A relation needs two endpoints, so a passage naming fewer than two known entities
#: cannot produce one. Skipping them is not an optimisation - calling the model on a
#: passage that provably cannot yield an edge is how a free tier gets exhausted before
#: the passages that can.
MIN_ENTITIES = 2

#: (provider, model), FREE FIRST - and that ordering is not cosmetic. The first version
#: of this ladder led with `deepseek/deepseek-chat`, which is paid, and a bulk run over
#: 849 passages exhausted the OpenRouter in-flight credit budget and then spent a 402 on
#: every remaining passage before falling through. Extraction is a bulk job with a cheap
#: per-item value, so it belongs on the free tier by default; the paid rungs exist so one
#: rate limit cannot cost the whole graph, not to be the default path.
TEXT_LADDER: list[tuple[str, str]] = [
    ("openrouter", "minimax/minimax-m3:free"),
    ("openrouter", "google/gemma-4-31b-it:free"),
    ("openrouter", "deepseek/deepseek-chat"),
    ("openai", "gpt-4o-mini"),
]

INSTRUCTION = """You extract relationships between named entities from an archive passage.

You will be given:
1. A closed list of entities that appear in the passage, each with an id.
2. A closed list of allowed relationship types.
3. The passage itself, inside a delimited evidence block.

Return ONLY JSON:

{"relations": [{"subject_id": "...", "predicate": "...", "object_id": "...",
                "qualifier": "optional short string such as 'since 336 AS'",
                "quote": "the exact sentence from the passage that states this"}]}

Rules:
- `subject_id` and `object_id` MUST both come from the entity list given to you. Never
  invent an id, and never use a name that is not in the list.
- `predicate` MUST come from the allowed list. If a relationship is real but has no
  matching predicate, omit it rather than choosing the closest one.
- Extract only what the passage STATES. Do not infer from world knowledge, and do not
  connect two entities merely because they are mentioned together.
- `quote` must be copied verbatim from the passage. If you cannot quote it, do not
  return it.
- A passage that states no relationship returns {"relations": []}. That is a correct and
  common answer.
"""


@dataclass
class ExtractionStats:
    """Counted, not estimated. Every drop reason is a separate number because 'the model
    returned garbage' and 'the model named an entity that was not in the passage' call
    for completely different fixes."""

    candidates: int = 0
    called: int = 0
    cached: int = 0
    failed: int = 0
    proposed: int = 0
    kept: int = 0
    dropped_unknown_entity: int = 0
    dropped_bad_predicate: int = 0
    dropped_self_loop: int = 0
    dropped_no_quote: int = 0
    dropped_quote_not_in_text: int = 0
    suspicious_spans: int = 0
    flagged_chunks: set[str] = field(default_factory=set)


@dataclass
class Candidate:
    chunk_id: str
    doc_id: str
    text: str
    authority_tier: int
    entities: list[Entity]


def load_candidates(
    chunks_path: Path, vocabulary: list[Entity], tiers: tuple[int, ...] = (3, 4, 5)
) -> list[Candidate]:
    """Narrative chunks naming at least two known entities.

    Uses the same exact, article-insensitive matcher as graph expansion, so a passage is
    a candidate for the same reason a query would reach it. No fuzzy matching: a
    misspelled name in prose is not evidence about the entity it resembles.
    """
    candidates: list[Candidate] = []
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("authority_tier") not in tiers:
            continue
        if row.get("source_type") in {"figure_plate", "wiki_image"}:
            continue
        present = entities_in_query(row.get("text", ""), vocabulary)
        if len(present) < MIN_ENTITIES:
            continue
        candidates.append(
            Candidate(
                chunk_id=row["chunk_id"],
                doc_id=row["doc_id"],
                text=row["text"],
                authority_tier=row["authority_tier"],
                entities=present,
            )
        )
    return candidates


def build_prompt(candidate: Candidate) -> tuple[str, list[tuple[str, str, str]]]:
    """The full user message, plus any instruction-like spans found in the passage."""
    roster = "\n".join(
        f'  {e.entity_id} = "{e.canonical_name}" ({e.type})' for e in candidate.entities
    )
    block = render([(candidate.chunk_id, candidate.text)])
    message = (
        f"{INSTRUCTION}\n\n"
        f"Entities present in this passage (the ONLY ids you may use):\n{roster}\n\n"
        f"Allowed predicates (the ONLY values you may use):\n"
        f"  {', '.join(sorted(PREDICATES))}\n\n"
        f"{block.text}"
    )
    return message, block.suspicious


def validate(proposed: list[dict], candidate: Candidate, stats: ExtractionStats) -> list[Relation]:
    """Keep only edges the passage can actually support.

    Every check here exists because the alternative is an edge that looks sourced and is
    not. An edge carrying a real `evidence_chunk_id` and a relationship the chunk never
    states is worse than no edge at all: it survives every downstream check we have.
    """
    allowed = {e.entity_id for e in candidate.entities}
    normalised_text = " ".join(candidate.text.lower().split())
    kept: list[Relation] = []

    for item in proposed:
        stats.proposed += 1
        if not isinstance(item, dict):
            stats.dropped_bad_predicate += 1
            continue

        subject = str(item.get("subject_id", ""))
        obj = str(item.get("object_id", ""))
        predicate = str(item.get("predicate", ""))
        quote = str(item.get("quote", "") or "")

        if subject not in allowed or obj not in allowed:
            stats.dropped_unknown_entity += 1
            continue
        if predicate not in PREDICATES:
            stats.dropped_bad_predicate += 1
            continue
        if subject == obj:
            stats.dropped_self_loop += 1
            continue
        if not quote.strip():
            stats.dropped_no_quote += 1
            continue
        if " ".join(quote.lower().split()) not in normalised_text:
            # A quote the passage does not contain means the model wrote the sentence it
            # wished were there. That is the failure this check exists to catch.
            stats.dropped_quote_not_in_text += 1
            continue

        qualifier = item.get("qualifier")
        kept.append(
            Relation(
                subject_id=subject,
                predicate=predicate,  # type: ignore[arg-type]
                object_id=obj,
                evidence_chunk_id=candidate.chunk_id,
                authority_tier=candidate.authority_tier,  # type: ignore[arg-type]
                confidence=LLM_CONFIDENCE,
                qualifier=str(qualifier)[:120] if qualifier else None,
            )
        )
        stats.kept += 1

    return kept


def extract_one(
    candidate: Candidate,
    client: LLMClient,
    stats: ExtractionStats,
    ladder: list[tuple[str, str]] | None = None,
) -> list[Relation]:
    """One passage in, validated relations out. Never raises — a failed passage is a
    passage without edges, not a failed run."""
    message, suspicious = build_prompt(candidate)
    if suspicious:
        stats.suspicious_spans += len(suspicious)
        stats.flagged_chunks.add(candidate.chunk_id)
        log.info(
            "instruction_like_text_in_source in %s: %s",
            candidate.chunk_id,
            "; ".join(f"{span!r} ({why})" for _, span, why in suspicious[:3]),
        )

    available = {p.name for p in client.providers if p.available()}
    rungs = [(p, m) for p, m in (ladder or TEXT_LADDER) if p in available]
    if not rungs:
        raise NoProviderConfiguredError

    for provider, model in rungs:
        try:
            response = client.complete(
                [{"role": "user", "parts": [{"type": "text", "text": message}]}],
                model=model,
                provider=provider,
                json_mode=True,
            )
        except Exception as exc:  # noqa: BLE001 - try the next rung
            log.warning("%s/%s failed on %s: %s", provider, model, candidate.chunk_id, exc)
            continue

        if response.cached:
            stats.cached += 1
        else:
            stats.called += 1

        try:
            payload = response.json_payload()
            proposed = payload.get("relations", []) if isinstance(payload, dict) else []
        except Exception as exc:  # noqa: BLE001 - unparseable is a drop, not a crash
            log.warning("unparseable payload for %s: %s", candidate.chunk_id, exc)
            stats.failed += 1
            return []

        return validate(proposed, candidate, stats)

    stats.failed += 1
    return []


def run(
    limit: int | None = None,
    workers: int = 4,
    ladder: list[tuple[str, str]] | None = None,
) -> tuple[list[Relation], ExtractionStats]:
    settings = get_settings()
    store = GraphStore()
    _, vocabulary = store.all_entities(limit=5000)

    candidates = load_candidates(settings.index_dir / "chunks.jsonl", vocabulary)
    if limit:
        candidates = candidates[:limit]

    stats = ExtractionStats(candidates=len(candidates))
    client = LLMClient()
    relations: list[Relation] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for found in pool.map(lambda c: extract_one(c, client, stats, ladder=ladder), candidates):
            relations.extend(found)

    return relations, stats


def print_stats(stats: ExtractionStats, relations: list[Relation]) -> None:
    dropped = (
        stats.dropped_unknown_entity
        + stats.dropped_bad_predicate
        + stats.dropped_self_loop
        + stats.dropped_no_quote
        + stats.dropped_quote_not_in_text
    )
    print(f"\ncandidates          {stats.candidates}")
    print(f"  llm calls         {stats.called} ({stats.cached} cached, {stats.failed} failed)")
    print(f"  relations proposed {stats.proposed}")
    print(f"  kept              {stats.kept}")
    print(f"  dropped           {dropped}")
    print(f"    unknown entity  {stats.dropped_unknown_entity}")
    print(f"    bad predicate   {stats.dropped_bad_predicate}")
    print(f"    self loop       {stats.dropped_self_loop}")
    print(f"    no quote        {stats.dropped_no_quote}")
    print(f"    quote not in text {stats.dropped_quote_not_in_text}")
    print(
        f"  instruction-like  {stats.suspicious_spans} spans "
        f"in {len(stats.flagged_chunks)} chunks"
    )

    if relations:
        from collections import Counter

        by_predicate = Counter(r.predicate for r in relations)
        print("\n  by predicate:")
        for predicate, count in by_predicate.most_common():
            print(f"    {predicate:14s} {count}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="only the first N candidate passages")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--write", action="store_true", help="merge the edges into the graph")
    parser.add_argument("--out", default="data/index/graph_llm_relations.jsonl")
    args = parser.parse_args()

    relations, stats = run(limit=args.limit, workers=args.workers)
    print_stats(stats, relations)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(r.model_dump_json() for r in relations) + "\n", encoding="utf-8")
    print(f"\nwrote {out} ({len(relations)} relations)")

    if args.write:
        store = GraphStore()
        before = store.counts()
        added = store.add_relations(relations)
        after = store.counts()
        print(f"graph relations {before[1]} -> {after[1]} ({added} new)")
        if added == 0 and relations:
            print("  (all already present - add_relations is idempotent by design)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
