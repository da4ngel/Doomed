"""Persist the entity graph to SQLite, traverse it with NetworkX.

WHY SQLite and not Neo4j: the whole graph is 203 entities and 379 relations. It fits in
memory many times over, and a graph database would add a service to start, a query
language to defend, and a dependency a judge must install - for no measurable benefit at
this scale. CLAUDE.md calls that infra tax, and it is.

WHY persist at all when `wiki_extract.extract()` is fast: `/v1/ready` must report real
counts without re-parsing 95 markdown files on every health check, and the LLM extraction
over `chronicles/` and `ephemera/` will append to this store rather than re-running. The
file is the accumulation point for both sources of edges.

Every edge keeps its `evidence_chunk_id` and `authority_tier` through storage, because
A4 resolves conflicts by tier and no answer may cite an edge that cannot name its source.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from src.api.schemas import Entity, Relation
from src.core.config import Settings, get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id      TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    type           TEXT NOT NULL,
    aliases        TEXT NOT NULL DEFAULT '',
    mention_count  INTEGER NOT NULL DEFAULT 0,
    doc_ids        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS relations (
    subject_id        TEXT NOT NULL,
    predicate         TEXT NOT NULL,
    object_id         TEXT NOT NULL,
    evidence_chunk_id TEXT NOT NULL,
    authority_tier    INTEGER NOT NULL,
    confidence        REAL NOT NULL DEFAULT 1.0,
    qualifier         TEXT,
    PRIMARY KEY (subject_id, predicate, object_id, evidence_chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_object  ON relations(object_id);
CREATE INDEX IF NOT EXISTS idx_relations_pred    ON relations(predicate);
"""


@dataclass
class Hop:
    """One step of a walk, carrying the evidence that licenses it."""

    subject_id: str
    predicate: str
    object_id: str
    evidence_chunk_id: str
    authority_tier: int
    qualifier: str | None = None

    def as_text(self, names: dict[str, str]) -> str:
        subject = names.get(self.subject_id, self.subject_id)
        obj = names.get(self.object_id, self.object_id)
        qualifier = f" ({self.qualifier})" if self.qualifier else ""
        return f"{subject} -{self.predicate}-> {obj}{qualifier}"


class GraphStore:
    """SQLite-backed entity graph with k-hop and path queries."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path or settings.index_dir / "graph.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    # -- writing ---------------------------------------------------------

    def replace_all(self, entities: dict[str, Entity], relations: list[Relation]) -> None:
        """Rebuild from scratch. Deterministic extraction means a rebuild is cheap and
        idempotent, which is safer than trying to diff two graph versions."""
        with self._connect() as conn:
            conn.execute("DELETE FROM relations")
            conn.execute("DELETE FROM entities")
            conn.executemany(
                "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.entity_id,
                        e.canonical_name,
                        e.type,
                        "|".join(e.aliases),
                        e.mention_count,
                        "|".join(e.doc_ids),
                    )
                    for e in entities.values()
                ],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO relations VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        r.subject_id,
                        r.predicate,
                        r.object_id,
                        r.evidence_chunk_id,
                        r.authority_tier,
                        r.confidence,
                        r.qualifier,
                    )
                    for r in relations
                ],
            )

    # -- reading ---------------------------------------------------------

    def counts(self) -> tuple[int, int]:
        with self._connect() as conn:
            entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            relations = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        return int(entities), int(relations)

    def entity(self, entity_id: str) -> Entity | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
        return _row_to_entity(row) if row else None

    def find_entities(self, name: str, limit: int = 10) -> list[Entity]:
        """Case-insensitive name lookup. Deliberately NOT fuzzy.

        Fuzzy matching on invented proper nouns is the single most dangerous thing this
        system could do: `greyfell_citadel` and `ironfell_citadel` are different places
        with different garrison figures, and silently resolving one to the other returns
        a wrong number with a genuine citation attached (addendum, Finding 13).
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entities WHERE LOWER(canonical_name) = LOWER(?) LIMIT ?",
                (name.strip(), limit),
            ).fetchall()
        return [_row_to_entity(r) for r in rows]

    def _edges_from(self, entity_id: str, undirected: bool = True) -> list[Hop]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM relations WHERE subject_id = ?", (entity_id,)
            ).fetchall()
            hops = [
                Hop(
                    r["subject_id"],
                    r["predicate"],
                    r["object_id"],
                    r["evidence_chunk_id"],
                    r["authority_tier"],
                    r["qualifier"],
                )
                for r in rows
            ]
            if undirected:
                # A question like "who won the War of Drowned Light" walks an edge
                # backwards - the `won` edge points from the victor to the war.
                back = conn.execute(
                    "SELECT * FROM relations WHERE object_id = ?", (entity_id,)
                ).fetchall()
                hops += [
                    Hop(
                        r["subject_id"],
                        r["predicate"],
                        r["object_id"],
                        r["evidence_chunk_id"],
                        r["authority_tier"],
                        r["qualifier"],
                    )
                    for r in back
                ]
        return hops

    def neighbors(
        self,
        entity_id: str,
        hops: int = 1,
        predicates: list[str] | None = None,
        max_nodes: int = 200,
    ) -> tuple[set[str], list[Hop]]:
        """k-hop expansion. Returns (entity ids reached, edges traversed).

        Capped at `max_nodes` because an unbounded expansion from a hub entity would
        swamp the evidence bundle and blow the token budget before A5 ever runs.
        """
        seen = {entity_id}
        edges: list[Hop] = []
        frontier = deque([(entity_id, 0)])

        while frontier and len(seen) < max_nodes:
            current, depth = frontier.popleft()
            if depth >= hops:
                continue
            for hop in self._edges_from(current):
                if predicates and hop.predicate not in predicates:
                    continue
                other = hop.object_id if hop.subject_id == current else hop.subject_id
                edges.append(hop)
                if other not in seen:
                    seen.add(other)
                    frontier.append((other, depth + 1))
        return seen, edges

    def paths(
        self, start_id: str, end_id: str, max_hops: int = 3, max_paths: int = 10
    ) -> list[list[Hop]]:
        """All simple paths up to `max_hops`, each step carrying its evidence.

        This is what makes a 1B answer show its working: the hop chain is rendered in the
        answer, so "A -> B because ...; B -> C because ..." is quotable rather than
        asserted.
        """
        results: list[list[Hop]] = []
        queue: deque[tuple[str, list[Hop], set[str]]] = deque([(start_id, [], {start_id})])

        while queue and len(results) < max_paths:
            current, trail, visited = queue.popleft()
            if len(trail) >= max_hops:
                continue
            for hop in self._edges_from(current):
                other = hop.object_id if hop.subject_id == current else hop.subject_id
                if other in visited:
                    continue
                extended = [*trail, hop]
                if other == end_id:
                    results.append(extended)
                    if len(results) >= max_paths:
                        break
                else:
                    queue.append((other, extended, visited | {other}))
        return results

    def distinct_paths(
        self, start_id: str, end_id: str, max_hops: int = 3, max_paths: int = 10
    ) -> list[tuple[list[Hop], list[str]]]:
        """Paths collapsed by their entity chain, with every supporting evidence id.

        The same chain attested by both an infobox row and a prose sentence is ONE route
        corroborated twice, not two independent routes. Reporting it as two would inflate
        the corroboration count A4 uses to break equal-tier conflicts - the same failure
        that made format twins dangerous.
        """
        grouped: dict[tuple[str, ...], tuple[list[Hop], list[str]]] = {}
        for path in self.paths(start_id, end_id, max_hops, max_paths * 4):
            key = tuple(
                part for hop in path for part in (hop.subject_id, hop.predicate, hop.object_id)
            )
            if key in grouped:
                grouped[key][1].extend(
                    e for e in (h.evidence_chunk_id for h in path) if e not in grouped[key][1]
                )
            else:
                grouped[key] = (path, [h.evidence_chunk_id for h in path])
            if len(grouped) >= max_paths:
                break
        return list(grouped.values())

    def all_entities(
        self, entity_type: str | None = None, limit: int = 1000
    ) -> tuple[int, list[Entity]]:
        """The whole vocabulary, for A1's normalisation. Returns (total, page).

        NOTE for callers: type `Title` is the catch-all and holds literals as well as
        names - years like "315 AS" and secret text become object nodes. A1 should
        normalise against the typed entities (Character, Faction, Location, Artifact,
        Event, Component), not against everything.
        """
        with self._connect() as conn:
            if entity_type:
                total = conn.execute(
                    "SELECT COUNT(*) FROM entities WHERE type = ?", (entity_type,)
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT * FROM entities WHERE type = ? ORDER BY canonical_name LIMIT ?",
                    (entity_type, limit),
                ).fetchall()
            else:
                total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
                rows = conn.execute(
                    "SELECT * FROM entities ORDER BY canonical_name LIMIT ?", (limit,)
                ).fetchall()
        return int(total), [_row_to_entity(r) for r in rows]

    def names(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT entity_id, canonical_name FROM entities").fetchall()
        return {r["entity_id"]: r["canonical_name"] for r in rows}

    def to_networkx(self):
        """Load the whole graph into NetworkX for algorithms we do not hand-roll."""
        import networkx as nx

        graph = nx.MultiDiGraph()
        with self._connect() as conn:
            for row in conn.execute("SELECT * FROM entities"):
                graph.add_node(row["entity_id"], name=row["canonical_name"], type=row["type"])
            for row in conn.execute("SELECT * FROM relations"):
                graph.add_edge(
                    row["subject_id"],
                    row["object_id"],
                    key=row["predicate"],
                    evidence_chunk_id=row["evidence_chunk_id"],
                    authority_tier=row["authority_tier"],
                    qualifier=row["qualifier"],
                )
        return graph


def _row_to_entity(row: sqlite3.Row) -> Entity:
    return Entity(
        entity_id=row["entity_id"],
        canonical_name=row["canonical_name"],
        type=row["type"],
        aliases=[a for a in row["aliases"].split("|") if a],
        mention_count=row["mention_count"],
        doc_ids=[d for d in row["doc_ids"].split("|") if d],
    )


def build(settings: Settings | None = None) -> tuple[int, int]:
    """Extract from the wiki and persist. Idempotent."""
    from src.graph.wiki_extract import extract, load_corpus_articles

    settings = settings or get_settings()
    report = extract(load_corpus_articles(settings.corpus_root / "wiki"))
    store = GraphStore(settings.index_dir / "graph.sqlite")
    store.replace_all(report.entities, report.relations)
    return store.counts()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="rebuild from the wiki")
    args = parser.parse_args()

    settings = get_settings()
    if args.build:
        entities, relations = build(settings)
        print(f"entities  : {entities}")
        print(f"relations : {relations}")
        print(f"\nwrote {settings.index_dir / 'graph.sqlite'}")
        return 0

    store = GraphStore(settings.index_dir / "graph.sqlite")
    entities, relations = store.counts()
    print(f"entities {entities}, relations {relations} (use --build to rebuild)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
