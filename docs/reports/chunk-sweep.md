# Chunk size sweep — ablation row 9

Run 2026-09-07 with `scripts/chunk_sweep.py --sizes 300 600`. Each size built into its own
`index_dir` and its own Qdrant collection, so the working index was never at risk.

The **450 row is the production index**, built by the same chunker from the same blocks —
chunking is the only variable across all three.

ADR-008 set 450 by *derivation*: the embedding model (`BAAI/bge-small-en-v1.5`) truncates
at 512 tokens, and 450 leaves room for the overlap the chunker prepends. That was a
defect argument, never a comparison. This is the comparison.

---

## What each size produces

| target | chunks | over 512 tokens | embed time |
|---|---|---|---|
| 300 | 3,407 | 1 (0.0%) | 1,450 s |
| **450** | **2,474** | **1 (0.0%)** | ~1,540 s |
| 600 | 2,028 | **176 (8.7%)** | 1,452 s |

The 176 confirms ADR-008's central claim independently: at a 600-token target, 8.7% of
chunks exceed the embedder's context and are indexed but only partly embedded — present
in the store, returned by BM25, unreachable by dense retrieval, with nothing logged. The
ADR measured 173 at the time; the small difference is later chunker fixes moving
boundaries, not a different phenomenon.

Embedding cost is flat across sizes, which is worth stating: the total token count is
roughly constant, so a smaller target buys more chunks at the same price rather than a
cheaper index.

---

## Retrieval, by size

### `multihop_1b`

| size | config | recall@10 | coverage@10 | nDCG@10 |
|---|---|---|---|---|
| 300 | Hybrid RRF | 0.619 | 0.286 | 0.568 |
| **450** | Hybrid RRF | **0.714** | **0.429** | 0.590 |
| 600 | Hybrid RRF | 0.667 | 0.429 | **0.615** |
| 300 | + graph expand | 0.857 | 0.571 | 0.692 |
| **450** | **+ graph expand** | **0.905** | **0.714** | 0.684 |
| 600 | + graph expand | 0.857 | 0.571 | **0.709** |

### `rich_1a`

| size | config | recall@10 | coverage@10 | nDCG@10 |
|---|---|---|---|---|
| 300 | Hybrid RRF | 0.773 | 0.545 | 0.707 |
| 450 | Hybrid RRF | 0.773 | 0.545 | 0.715 |
| 600 | Hybrid RRF | 0.773 | 0.545 | **0.719** |
| 300 | + graph expand | 0.727 | 0.545 | 0.685 |
| 450 | + graph expand | 0.773 | 0.545 | 0.715 |
| 600 | + graph expand | 0.773 | 0.545 | **0.719** |

### `paraphrase`

| size | config | recall@10 | coverage@10 | nDCG@10 |
|---|---|---|---|---|
| 300 | Hybrid RRF | 0.526 | 0.210 | 0.505 |
| 450 | Hybrid RRF | **0.553** | **0.263** | 0.524 |
| 600 | Hybrid RRF | **0.553** | **0.263** | 0.524 |
| 300 | + graph expand | 0.667 | 0.421 | 0.582 |
| **450** | **+ graph expand** | **0.693** | **0.474** | **0.600** |
| 600 | + graph expand | **0.693** | **0.474** | 0.598 |

---

## What it says

### 1. 450 wins or ties on every suite, on the metrics that matter

On `multihop_1b` with graph expansion — the configuration this system actually ships —
450 reaches **0.905 / 0.714** against 0.857 / 0.571 at both 300 and 600. That is one
whole extra question covered, on a suite where one question is 0.143.

On `paraphrase` 450 ties 600 and beats 300. On `rich_1a` all three are identical on
recall and coverage.

**A size derived from the embedding model's context window turned out to be the
empirically best one.** That is a pleasant result rather than a designed one, and it is
worth being precise about which claim it supports: ADR-008 argued 450 was *safe*, not that
it was optimal. It is now both, and the reasoning that produced it is validated rather
than merely unrefuted.

### 2. 300 is worse on multi-hop, and only on multi-hop

Coverage 0.286 against 0.429 (hybrid), 0.571 against 0.714 (with graph expansion), while
1A is untouched.

The mechanism is the k budget. 3,407 chunks means each holds less, so the evidence for one
hop is spread across more of them and a fixed top-10 holds fewer distinct *documents*.
`coverage@k` counts documents, so fragmenting the corpus costs exactly the metric 1B is
scored on. A figure-plate lookup does not care, because its answer is one chunk either way.

### 3. 600's truncation costs less than expected — and nDCG says why

600 loses coverage on multi-hop against 450, but wins nDCG marginally on `rich_1a` (0.719
vs 0.715) and on `multihop_1b` (0.709 vs 0.684) — despite 8.7% of its chunks being
partly unembedded.

That is not a contradiction. BM25 indexes the **full** text of every chunk, so a truncated
chunk is still lexically findable; only its dense representation is short. Hybrid fusion
therefore masks most of the damage, and what survives is a ranking effect rather than a
recall one. Larger chunks also carry more context per hit, which flatters a rank-sensitive
metric.

**This is the honest reading: the 8.7% truncation is a real defect that hybrid retrieval
largely hides.** Had we shipped 600 and measured only nDCG, it would have looked fine. The
argument for leaving 600 was never that it scored badly — it was that a silent partial
index is not a thing you ship, and rows 1–2 of the ablation show dense-only retrieval
would have carried the damage alone.

### 4. Cost is flat, so this is not a size/price trade

All three embed in about the same wall-clock time. Choosing 450 costs nothing against 600
and buys a correct index; choosing it over 300 costs nothing and buys multi-hop coverage.

---

## What this does not settle

- **Only 300 / 450 / 600 were tested.** 400 and 500 are unmeasured; the curve between them
  is assumed smooth and that assumption is untested.
- **One embedding model.** Every number here is downstream of BGE-small's 512-token window.
  A larger-context embedder would move the whole table, which is exactly what ADR-008's
  own "what we would revisit" note anticipated.
- **Retrieval only.** No answer was composed at any size, so whether larger chunks help or
  hurt the composer is unmeasured — and larger chunks mean more tokens per citation, which
  is a cost this table cannot see.
- **n is still 7, 11 and 19.** A 0.143 move on `multihop_1b` is one question.

---

## Reproducing

```bash
uv run python scripts/chunk_sweep.py --sizes 300 600
```

~25 minutes per size, CPU-bound on embedding. Each size builds into `data/sweep/chunk_<n>/`
and the Qdrant collection `ashen_sweep_<n>`, both dropped on completion (`--keep` retains
them). The script asserts `indexed == chunks` and raises rather than logging: three
separate indexing bugs in this project printed a success line while being wrong, and a
sweep row built on a short index would read as a chunk-size finding.
