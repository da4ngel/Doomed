"""Select visual evidence by exact linked subject while preserving raw retrieval traces."""

from src.agents.analyst import Analysis
from src.api.schemas import SearchHit
from src.synthesis.visuals import words


def focused_chunks(analysis: Analysis, chunks: list[SearchHit]) -> list[SearchHit]:
    """Figure source identity is stronger than incidental mentions inside its description."""
    if not analysis.requires_visual or not analysis.seed_entities:
        return chunks
    names = [words(seed.surface).removeprefix("the ") for seed in analysis.seed_entities]
    selected = []
    for chunk in chunks:
        identity = " " + words(" ".join([chunk.doc_id, chunk.title, *chunk.section_path])) + " "
        if any(" " + name + " " in identity for name in names if name):
            selected.append(chunk)
    # An unresolved identity must not turn retrieved evidence into a fabricated match.
    return selected or chunks
