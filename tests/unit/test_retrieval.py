"""Tests for fusion, sparse retrieval and the search seam.

These avoid the dense index deliberately: the embedded Qdrant store is single-process, so
a test that opened it would fight the indexer for the file lock. Fusion and BM25 carry
the logic worth pinning anyway - the vector store is a thin wrapper over a library.
"""

from __future__ import annotations

import pytest

from src.api.schemas import Chunk, SearchFilters, SearchRequest, SearchResponse
from src.indexing.bm25_store import BM25Store, tokenize
from src.retrieval.rrf import RRF_K, reciprocal_rank_fusion


def _hit(chunk_id: str, score: float = 1.0, **payload):
    return (chunk_id, score, {"text": chunk_id, **payload})


# --------------------------------------------------------------------------
# Reciprocal Rank Fusion
# --------------------------------------------------------------------------


def test_a_document_ranked_by_both_retrievers_outranks_one_ranked_by_either() -> None:
    """The core premise of hybrid search, asserted rather than assumed."""
    dense = [_hit("a"), _hit("b")]
    sparse = [_hit("c"), _hit("a")]
    fused = reciprocal_rank_fusion(dense, sparse, limit=5)
    assert fused[0].chunk_id == "a"


def test_fusion_uses_rank_not_score() -> None:
    """BM25 scores are unbounded and cosine is in [-1, 1]; mixing the numbers would need
    a normalisation we would then have to defend."""
    dense = [_hit("a", score=1000.0)]
    sparse = [_hit("b", score=0.0001)]
    fused = reciprocal_rank_fusion(dense, sparse, limit=5)
    assert fused[0].score == fused[1].score == pytest.approx(1.0 / (RRF_K + 1))


def test_each_hit_reports_which_retriever_found_it() -> None:
    """The ablation must attribute a win to the component that earned it."""
    fused = {h.chunk_id: h for h in reciprocal_rank_fusion([_hit("a")], [_hit("b")], limit=5)}
    assert fused["a"].dense_rank == 1 and fused["a"].sparse_rank is None
    assert fused["b"].sparse_rank == 1 and fused["b"].dense_rank is None


def test_an_empty_retriever_is_a_valid_configuration() -> None:
    """Rows 1 and 2 of the ablation are BM25-only and dense-only. They must not need a
    separate code path, or the row measures two changes at once."""
    assert [h.chunk_id for h in reciprocal_rank_fusion([], [_hit("x")], limit=5)] == ["x"]
    assert [h.chunk_id for h in reciprocal_rank_fusion([_hit("y")], [], limit=5)] == ["y"]
    assert reciprocal_rank_fusion([], [], limit=5) == []


def test_fusion_is_deterministic_on_ties() -> None:
    """A non-deterministic order would make eval deltas unreproducible."""
    dense = [_hit("b"), _hit("a")]
    first = [h.chunk_id for h in reciprocal_rank_fusion(dense, [], limit=5)]
    second = [h.chunk_id for h in reciprocal_rank_fusion(dense, [], limit=5)]
    assert first == second


def test_limit_is_respected() -> None:
    dense = [_hit(str(i)) for i in range(20)]
    assert len(reciprocal_rank_fusion(dense, [], limit=5)) == 5


# --------------------------------------------------------------------------
# Tokenisation and BM25
# --------------------------------------------------------------------------


def test_hyphenated_proper_nouns_survive_tokenisation() -> None:
    """`thrice-bound` splitting apart would discard the distinction between the Edge
    (94) and the Lantern (55)."""
    assert "thrice-bound" in tokenize("The Thrice-Bound Edge")


def test_tokenizer_lowercases_and_drops_punctuation() -> None:
    assert tokenize("Greyfell Citadel, 3,695 souls.") == [
        "greyfell",
        "citadel",
        "3",
        "695",
        "souls",
    ]


def _chunk(chunk_id: str, text: str, tier: int = 2, source: str = "wiki") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=chunk_id,
        text=text,
        authority_tier=tier,
        source_type=source,
        token_count=len(text.split()),
    )


@pytest.fixture()
def sparse_store(tmp_path, monkeypatch) -> BM25Store:
    from src.core.config import Settings

    settings = Settings(qdrant_path=tmp_path / "q")
    object.__setattr__(settings, "index_dir", tmp_path)
    store = BM25Store(settings)
    store.build(
        [
            _chunk(
                "edge", "The Thrice-Bound Edge attunement cost 94 vitae-grains", 1, "figure_plate"
            ),
            _chunk(
                "lantern",
                "The Thrice-Bound Lantern attunement cost 55 vitae-grains",
                1,
                "figure_plate",
            ),
            _chunk("greyfell", "Greyfell Citadel recorded garrison strength 3,695"),
            _chunk("ironfell", "Ironfell Citadel garrison strength 1,096"),
        ]
    )
    return store


def test_bm25_separates_confusable_proper_nouns(sparse_store: BM25Store) -> None:
    """Finding 8: Edge vs Lantern differ by one token, and dense similarity pulls them
    together. Exact lexical matching is what tells them apart."""
    top = sparse_store.search("Thrice-Bound Lantern attunement cost", k=2)
    assert top[0][0] == "lantern"


def test_bm25_separates_the_citadel_decoys(sparse_store: BM25Store) -> None:
    """Finding 13: greyfell_citadel (3,695, image only) vs ironfell_citadel (1,096)."""
    top = sparse_store.search("Greyfell Citadel garrison strength", k=2)
    assert top[0][0] == "greyfell"


def test_filters_narrow_by_tier(sparse_store: BM25Store) -> None:
    results = sparse_store.search("attunement cost", k=5, filters=SearchFilters(authority_tier=[1]))
    assert results
    assert all(sparse_store.metadata(cid)["authority_tier"] == 1 for cid, _, _ in results)


def test_filters_do_not_silently_shrink_k(sparse_store: BM25Store) -> None:
    """Post-filtering would return fewer than k and quietly change what recall measures."""
    unfiltered = sparse_store.search("citadel garrison strength", k=2)
    filtered = sparse_store.search(
        "citadel garrison strength", k=2, filters=SearchFilters(source_type=["wiki"])
    )
    assert len(unfiltered) == 2
    assert len(filtered) == 2


def test_an_empty_query_returns_nothing_rather_than_raising(sparse_store: BM25Store) -> None:
    assert sparse_store.search("   ", k=5) == []


# --------------------------------------------------------------------------
# The seam
# --------------------------------------------------------------------------


def test_search_endpoint_rejects_an_empty_query() -> None:
    from fastapi.testclient import TestClient

    from src.api.main import app

    response = TestClient(app).post("/v1/search", json={"query": "   "})
    assert response.status_code == 422


def test_search_contract_is_reachable_in_the_openapi_schema() -> None:
    """P2 imports this into Postman from the link; if it vanishes, the seam is broken."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    schema = TestClient(app).get("/openapi.json").json()
    assert "/v1/search" in schema["paths"]
    assert "post" in schema["paths"]["/v1/search"]


#: The seam as P2 first coded against it. A field may be ADDED (ADR-009) but never
#: removed or renamed, so this list only ever grows - and it grows in the same commit
#: as the ADR that justifies it.
ORIGINAL_RESPONSE_FIELDS = {"hits", "total", "mode", "reranked", "latency_ms"}
ORIGINAL_REQUEST_FIELDS = {"query", "mode", "k", "rerank", "expand", "filters"}


def test_the_seam_never_removes_a_field() -> None:
    """The frozen seam: P2 codes against these fields.

    Asserting a superset rather than equality is deliberate. Exact equality failed on
    an additive, defaulted change that broke nobody, which trains people to edit the
    test rather than read it. What actually matters to a caller is that nothing they
    already use disappears.
    """
    response = SearchResponse(hits=[], total=0, mode="hybrid", reranked=False, latency_ms=1)
    assert ORIGINAL_RESPONSE_FIELDS <= set(response.model_dump())
    assert ORIGINAL_REQUEST_FIELDS <= set(SearchRequest(query="x").model_dump())


def test_every_field_added_since_the_freeze_is_optional() -> None:
    """The other half of the guarantee: a request written before a field existed must
    still validate, and must still mean what it meant. A required addition would break
    every caller silently at deploy time.
    """
    request = SearchRequest(query="x")
    for field in set(request.model_dump()) - ORIGINAL_REQUEST_FIELDS:
        assert not SearchRequest.model_fields[field].is_required(), field

    response = SearchResponse()
    for field in set(response.model_dump()) - ORIGINAL_RESPONSE_FIELDS:
        assert not SearchResponse.model_fields[field].is_required(), field


def test_expansion_defaults_to_off_so_old_requests_behave_identically() -> None:
    request = SearchRequest(query="x")
    assert request.expand is False
    assert SearchResponse().expanded == 0


# --------------------------------------------------------------------------
# BM25 over-fetch depth
# --------------------------------------------------------------------------


def test_an_empty_filter_object_does_not_count_as_filtering() -> None:
    """The 5x over-fetch is for filtered searches. It used to fire on every search.

    SearchRequest.filters is built with default_factory, so it is never None, and a
    plain pydantic model has no __bool__ - an empty SearchFilters is truthy. So
    `k * 5 if filters else k` took the 5x branch always, on top of the 4x the caller
    already asks for: every search ran BM25 at k*20 depth, filtered or not.
    """
    from src.api.schemas import SearchFilters
    from src.indexing.bm25_store import BM25Store

    assert (
        bool(SearchFilters()) is True
    ), "if this ever becomes falsy the bug is gone and this test can go with it"
    assert BM25Store._is_active(SearchFilters()) is False
    assert BM25Store._is_active(None) is False


def test_a_real_filter_still_triggers_the_over_fetch() -> None:
    """The guard must be narrow: filtering still needs the deeper candidate pool, or
    post-filtering silently returns fewer than k results."""
    from src.api.schemas import SearchFilters
    from src.indexing.bm25_store import BM25Store

    assert BM25Store._is_active(SearchFilters(authority_tier=[1])) is True
    assert BM25Store._is_active(SearchFilters(source_type=["figure_plate"])) is True
    assert BM25Store._is_active(SearchFilters(doc_id=["wiki/x.md"])) is True
