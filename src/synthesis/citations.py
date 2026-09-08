"""Citation metadata comes from the HTTP seam, never the model's bibliography."""

import hashlib
import re

from src.api.schemas import Citation, SearchHit

#: Characters a model routinely substitutes when it reproduces a quote: curly quotes for
#: straight ones, en/em dashes for hyphens. Each maps to a class matching any of them.
_INTERCHANGEABLE = [
    "'‘’ʼ",
    '"“”',
    "-‐‑‒–—",
]


def find_verbatim_span(quote: str, text: str) -> str | None:
    """The real span in `text` that `quote` refers to, or None if there is none.

    WHY this exists: the composer used to test `quote in text` byte-for-byte and discard
    the whole claim on failure. Models reliably reproduce the WORDS of a quote and
    unreliably reproduce its whitespace and punctuation - a line break becomes a space, a
    straight apostrophe becomes a curly one. A multi-hop claim needs one quote per hop, so
    its odds of surviving that test are the single-quote odds raised to the number of
    hops, which is why multi-hop answers vanished while single-fact ones passed.

    The returned span is sliced out of `text` itself, never reconstructed from the
    model's version. So the citation stays a genuinely verbatim source span, its sha256
    still means something, and the anti-fabrication guarantee is unchanged: a quote that
    does not actually occur still returns None.
    """
    if quote in text:
        return quote
    tokens = quote.split()
    if not tokens:
        return None
    pattern = r"\s+".join(_flexible(token) for token in tokens)
    match = re.search(pattern, text)
    return match.group(0) if match else None


def _flexible(token: str) -> str:
    """Escape a token, letting interchangeable punctuation match any of its variants."""
    out = []
    for char in token:
        for group in _INTERCHANGEABLE:
            if char in group:
                out.append(f"[{re.escape(group)}]")
                break
        else:
            out.append(re.escape(char))
    return "".join(out)


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
