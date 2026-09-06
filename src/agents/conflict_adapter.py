"""Connect P1's real A4 ABI without importing the graph or altering source text."""

from __future__ import annotations

from collections.abc import Callable

from src.api.schemas import Chunk, Entity, EntityVocabularyResponse, SearchHit
from src.synthesis.conflicts import MergeReport, detect_conflicts


class Vocabulary:
    """A1 and A4 share one complete, validated HTTP vocabulary per request."""

    def __init__(self, fetch: Callable[[], object]) -> None:
        self.fetch = fetch
        self._entities: list[Entity] | None = None

    def __call__(self) -> list[Entity]:
        if self._entities is None:
            response = EntityVocabularyResponse.model_validate(self.fetch())
            if response.total != len(response.entities):
                raise ValueError("Entity vocabulary is truncated; normalization is unsafe")
            if not any(e.type != "Title" for e in response.entities):
                raise ValueError("Entity vocabulary has no named entities")
            self._entities = response.entities
        return self._entities


class ConflictAdapter:
    def __init__(self, vocabulary: Callable[[], list[Entity]]) -> None:
        self.vocabulary = vocabulary

    def __call__(self, hits: list[SearchHit]) -> MergeReport:
        typed: dict[str, str] = {
            e.canonical_name: e.type for e in self.vocabulary() if e.type != "Title"
        }
        if not typed:
            raise ValueError("Conflict attribution requires the entity vocabulary")
        # Only contract translation: no fabricated text, block IDs or graph metadata.
        chunks = [
            Chunk(
                chunk_id=h.chunk_id,
                doc_id=h.doc_id,
                text=h.text,
                page_span=(h.page, h.page) if h.page is not None else None,
                section_path=h.section_path,
                authority_tier=h.authority_tier,
                source_type=h.source_type,
                asset_ids=h.asset_ids,
            )
            for h in hits
        ]
        return detect_conflicts(chunks, typed)
