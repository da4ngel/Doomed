"""Recovering a quote the model reproduced imperfectly.

The composer used to test `quote in chunk.text` byte-for-byte and discard the WHOLE
claim on any failure. Models reproduce the words of a quote reliably and its whitespace
and punctuation unreliably. A multi-hop claim needs one quote per hop, so its survival
odds are the single-quote odds raised to the number of hops — which is why multi-hop
answers vanished while single-fact ones passed.
"""

from __future__ import annotations

from src.synthesis.citations import find_verbatim_span

TEXT = (
    "The Iron-Ring Cartel was the victor\n"
    "of the Leaden Accord, sealed in 402 AS by Ederon Fellgard's hand."
)


def test_an_exact_quote_is_returned_unchanged() -> None:
    assert find_verbatim_span("the victor", TEXT) == "the victor"


def test_a_line_break_flattened_to_a_space_is_recovered() -> None:
    """The single most common way a model mangles a quote."""
    found = find_verbatim_span("the victor of the Leaden Accord", TEXT)
    assert found == "the victor\nof the Leaden Accord"
    assert found in TEXT, "the span must be sliced from the text, not rebuilt"


def test_interchangeable_punctuation_is_recovered() -> None:
    """En dash for hyphen, curly apostrophe for straight — both are model habits."""
    assert find_verbatim_span("Iron–Ring Cartel", TEXT) == "Iron-Ring Cartel"
    assert find_verbatim_span("Fellgard’s hand", TEXT) == "Fellgard's hand"


def test_a_quote_that_is_not_there_still_fails() -> None:
    """The anti-fabrication guarantee is the whole point and must not be relaxed."""
    assert find_verbatim_span("the Silent Choir was the victor", TEXT) is None
    assert find_verbatim_span("sealed in 403 AS", TEXT) is None


def test_the_recovered_span_is_always_a_real_substring() -> None:
    """Whatever comes back is sliced out of the source, so a Citation built from it is
    genuinely verbatim and its excerpt_sha256 still means something."""
    for quote in [
        "the victor of the Leaden Accord",
        "Iron–Ring Cartel",
        "Fellgard’s hand",
    ]:
        span = find_verbatim_span(quote, TEXT)
        assert span is not None and span in TEXT


def test_an_empty_quote_matches_nothing() -> None:
    assert find_verbatim_span("   ", TEXT) is None


def test_a_recovered_span_can_build_a_citation() -> None:
    """The end-to-end property: citation_for re-checks that the excerpt is verbatim, so a
    span that fails that check would raise and lose the claim anyway."""
    from src.api.schemas import SearchHit
    from src.synthesis.citations import citation_for

    hit = SearchHit(
        chunk_id="c1",
        doc_id="wiki/leaden_accord.md",
        title="The Leaden Accord",
        text=TEXT,
        score=1.0,
        authority_tier=2,
        source_type="wiki",
    )
    span = find_verbatim_span("the victor of the Leaden Accord", TEXT)
    assert span is not None
    citation = citation_for(hit, span)
    assert citation.excerpt in TEXT


ELIDED = (
    "No particular operation is attributed to Ederon Fellgard in the established "
    "record. Ederon Fellgard is a member of [[The Iron-Ring Cartel]]. The membership "
    "is a direct part of the character's canonical identity."
)


def test_an_elided_quote_is_recovered() -> None:
    """Models quote the way people do, joining two real spans with an ellipsis.

    Requiring contiguity rejected those outright, and it was the most common reason a
    multi-hop claim was dropped: 1b_005 and 1b_007 both failed on quotes of the shape
    'Isolde Mournvale... belongs to The Silent Choir.'
    """
    span = find_verbatim_span("attributed to Ederon Fellgard... is a member of", ELIDED)
    assert span is not None
    assert span in ELIDED, "the span must be sliced from the source"
    assert "established record" in span, "the elided middle is included, not hidden"


def test_an_ellipsis_attached_to_a_word_is_handled() -> None:
    """'Sapper...' - the elision glued to the preceding token."""
    assert find_verbatim_span("record. Ederon Fellgard... member of", ELIDED) is not None


def test_an_ellipsis_cannot_stitch_unrelated_spans() -> None:
    """The gap is bounded. Without that, 'A ... B' would match any A and any B in the
    chunk and could support a claim neither fragment makes."""
    assert find_verbatim_span("Ederon Fellgard... rules Gloamreach", ELIDED) is None


def test_an_ellipsis_alone_matches_nothing() -> None:
    assert find_verbatim_span("...", ELIDED) is None
    assert find_verbatim_span("... ...", ELIDED) is None
