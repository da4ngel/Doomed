"""Citation metadata comes from the HTTP seam, never the model's bibliography."""

import hashlib

from src.api.schemas import Citation, SearchHit


def citation_for(chunk: SearchHit, excerpt: str) -> Citation:
    if excerpt not in chunk.text:
        raise ValueError("Citation excerpt must be a verbatim source span")
    digest = hashlib.sha256(excerpt.encode()).hexdigest()
    identity = hashlib.sha256((chunk.chunk_id + "\0" + excerpt).encode()).hexdigest()[:16]
    return Citation(
        id=f"cite_{identity}",
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        title=chunk.title,
        page=chunk.page,
        bbox=chunk.bbox,
        section_path=chunk.section_path,
        source_type=chunk.source_type,
        authority_tier=chunk.authority_tier,
        excerpt=excerpt,
        excerpt_sha256=digest,
        score=chunk.score,
    )
