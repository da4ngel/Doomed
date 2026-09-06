# Retrieval ablation — measured

Run 2026-09-06 (UTC) against the full index: 236 documents, 2,474 chunks, 2,474 dense vectors,
BM25 over the same chunks. Gold is hand-authored (`eval/suites/`), k = 10.

Four configurations of **one** `Retriever.search` function, differing only by request —
so each row measures one change, not two.

---

## The table

### `multihop_1b` — 7 questions, each needing ≥2 documents

| # | Config | recall@10 | **coverage@10** | nDCG@10 | MRR | p95 ms |
|---|---|---|---|---|---|---|
| 1 | BM25 only | 0.595 | 0.143 | 0.535 | 0.655 | 0 |
| 2 | Dense only | 0.476 | 0.000 | 0.509 | 0.833 | 136 |
| 3 | **Hybrid RRF** | **0.714** | **0.429** | **0.590** | 0.762 | 144 |
| 4 | Hybrid + rerank | 0.500 | 0.143 | 0.475 | 0.714 | 2,513 |

### `rich_1a` — 11 questions, answers inside images

| # | Config | recall@10 | coverage@10 | nDCG@10 | MRR | p95 ms |
|---|---|---|---|---|---|---|
| 1 | BM25 only | 0.727 | 0.545 | 0.664 | 0.730 | 1 |
| 2 | Dense only | 0.773 | 0.545 | 0.693 | 0.780 | 148 |
| 3 | Hybrid RRF | 0.773 | 0.545 | 0.715 | 0.803 | 151 |
| 4 | **Hybrid + rerank** | 0.773 | 0.545 | **0.779** | **0.939** | 2,772 |

### `contradiction_1c` — 2 questions (n is small; treat as directional)

| # | Config | recall@10 | coverage@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|
| 1 | BM25 only | 1.000 | 1.000 | 0.644 | 0.550 |
| 2 | Dense only | 1.000 | 1.000 | 0.566 | 0.417 |
| 3 | Hybrid RRF | 0.500 | 0.500 | 0.500 | 0.500 |
| 4 | Hybrid + rerank | 1.000 | 1.000 | 0.431 | 0.250 |

`unanswerable` and `adversarial` carry no gold documents by construction — they score
refusal behaviour, not retrieval, and are excluded from this table rather than reported
as zeros.

---

## What the numbers say

### 1. Hybrid beats both of its own components on multi-hop

**recall 0.714 against 0.595 (BM25) and 0.476 (dense); coverage 0.429 against 0.143 and
0.000.** This is the clearest result in the table and it is not a small margin — hybrid
covers three times as many 1B questions as BM25 alone and infinitely more than dense
alone, which covers none.

The mechanism is visible in the per-question failures. Dense alone loses `1b_009` because
"Iron-Ring Cartel" and "Purge of Blackport" are lexically distinctive and semantically
bland; BM25 alone loses `1b_006` and `1b_005` because "the faction that won" is a
semantic relation with no shared vocabulary. Each retriever fails on what the other is
for.

### 2. Reranking helps 1A and *actively harms* 1B — the most useful finding here

| | 1A nDCG | 1A MRR | 1B recall | 1B coverage |
|---|---|---|---|---|
| Hybrid RRF | 0.715 | 0.803 | 0.714 | 0.429 |
| Hybrid + rerank | **0.779** | **0.939** | **0.500** | **0.143** |

On 1A the cross-encoder is worth having: MRR 0.803 → 0.939 means the right plate moves to
rank 1 almost every time.

On 1B it destroys coverage — 0.429 → 0.143, a two-thirds loss.

**Why, mechanically:** a cross-encoder scores each document's relevance *to the query,
independently*. A multi-hop question needs documents that are individually weak matches
but collectively necessary — the second hop's article often does not mention the
question's subject at all. Reranking correctly identifies those as less relevant and
demotes them out of the top-k. It is optimising exactly the wrong objective for
`coverage@k`.

**Consequence for the router:** rerank should be **on for figure and single-lookup
intents, off for multi-hop**. That is a routing rule derived from a measurement, not a
preference — and it is why the router takes `intent` from A1 rather than always applying
the strongest pipeline.

### 3. Rerank costs ~2.4 seconds of p95 and buys nothing on recall

p95 goes from ~150 ms to ~2,500 ms. On 1A it buys ranking quality (nDCG, MRR) and no
recall at all — recall@10 is 0.773 in both rows. If latency matters more than the top
position, rows 3 and 4 retrieve the same documents.

### 4. `coverage@k` earns its place

On 1B, recall@10 of 0.595 (BM25) sounds survivable. `coverage@10` of **0.143** says one
question in seven actually has all of its evidence present — the other six are
unanswerable no matter how good the composer is.

Those two numbers describe the same run. Reporting only recall would have hidden the
problem the graph layer exists to solve.

---

## What is still missing from this table

Rows 5–9 of the planned ablation need components that are not built yet:

| Row | Blocked on |
|---|---|
| 5. + neighbour/section expansion | `expand.py` |
| 6. + graph expansion (1B) | wiring `/v1/graph/*` into retrieval |
| 7. + agentic loop (1C) | P2's orchestrator |
| 8. + conflict layer | A4 exists; needs the answer path to consume it |
| 9. chunk 300 / 450 / 600 sweep | one re-index per size, ~20 min each |

Row 6 is the one to watch: **coverage@10 = 0.429 is the number graph expansion has to
beat**, and it is the reason the graph exists at all.

---

## Reproducing

```bash
uv run python -m eval.runner --suite all --ablation --out docs/reports/ablation-retrieval.json
uv run python -m eval.runner --suite multihop_1b --ablation --failures
```

The harness refuses to score a configuration whose index is empty. An earlier run of this
table reported dense@10 = 0.000 across every suite because `QDRANT_URL` pointed at a
service the vectors had not been built into, and an absent collection returns `[]` rather
than raising — so the run completed and printed a table of zeros. That guard exists
because of it.
