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
    pattern = _pattern_for(tokens)
    if pattern is None:
        return None
    match = re.search(pattern, text)
    return match.group(0) if match else None


#: How much source text an ellipsis may skip over. A quotation elides a clause, not half
#: a document: without a bound, "A ... B" would match any A and any B in the chunk and
#: could stitch together a span supporting a claim neither part makes.
_MAX_ELISION = 400

_ELLIPSIS = re.compile(r"^(?:\.\.\.|…)[.…]*$")


def _pattern_for(tokens: list[str]) -> str | None:
    """Regex for these tokens, treating `...` as an elision the source may fill in.

    Models quote the way people do - "he serves as a Sapper... and is a member of X" -
    joining two real spans with an ellipsis. Requiring contiguity rejected those
    outright, and it was the single most common reason a multi-hop claim was dropped.

    The span returned still comes from the source and still CONTAINS the elided middle,
    so the citation shows a reader everything between the fragments; nothing is hidden by
    accepting the quote. The gap is bounded so an ellipsis cannot reach across a chunk.
    """
    parts: list[str] = []
    for token in tokens:
        stripped = token.strip(".…")
        if _ELLIPSIS.match(token):
            parts.append("GAP")
        elif stripped and token != stripped and _ELLIPSIS.match(token[len(stripped) :]):
            # "Sapper..." - a word with the elision attached to it.
            parts.append(_flexible(stripped))
            parts.append("GAP")
        else:
            parts.append(_flexible(token))
    if all(part == "GAP" for part in parts):
        return None

    out: list[str] = []
    for index, part in enumerate(parts):
        if part == "GAP":
            continue
        if index and parts[index - 1] == "GAP":
            out.append(rf"[\s\S]{{0,{_MAX_ELISION}}}?")
        elif index:
            out.append(r"\s+")
        out.append(part)
    return "".join(out)


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
