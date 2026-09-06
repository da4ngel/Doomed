# Retrieval ablation — measured

Run 2026-09-07 against the full index: 236 documents, 2,474 chunks, 2,474 dense vectors,
BM25 over the same chunks, and a graph of 198 entities and **572 relations** — 379
deterministic wiki edges plus 193 LLM-extracted ones. Expansion spends slots on the wiki
edges only; §6 explains why, with the number. Gold is hand-authored (`eval/suites/`),
k = 10.

Seven configurations of **one** `Retriever.search` function, differing only by request —
so each row measures one change, not two.

Rows 5–7 spend the **same k** as row 3: expansion evicts the weakest base hits rather than
extending the list (ADR-009). Appending would have scored row 6 on more evidence than
row 3 and credited the graph for the difference.

---

## The table

### `multihop_1b` — 7 questions, each needing ≥2 documents

| # | Config | recall@10 | **coverage@10** | nDCG@10 | MRR | p95 ms |
|---|---|---|---|---|---|---|
| 1 | BM25 only | 0.595 | 0.143 | 0.535 | 0.655 | 0 |
| 2 | Dense only | 0.476 | 0.000 | 0.509 | 0.833 | 127 |
| 3 | Hybrid RRF | 0.714 | 0.429 | 0.590 | 0.762 | 124 |
| 4 | Hybrid + rerank | 0.500 | 0.143 | 0.475 | 0.714 | 2,463 |
| 5 | + section expand | 0.643 | 0.286 | 0.556 | 0.762 | 135 |
| 6 | **+ graph expand** | **0.905** | **0.714** | **0.684** | 0.762 | 144 |
| 7 | + both expands | 0.881 | 0.714 | 0.677 | 0.762 | 123 |

### `rich_1a` — 11 questions, answers inside images

| # | Config | recall@10 | coverage@10 | nDCG@10 | MRR | p95 ms |
|---|---|---|---|---|---|---|
| 1 | BM25 only | 0.727 | 0.545 | 0.664 | 0.730 | 0 |
| 2 | Dense only | 0.773 | 0.545 | 0.693 | 0.780 | 129 |
| 3 | Hybrid RRF | 0.773 | 0.545 | 0.715 | 0.803 | 127 |
| 4 | **Hybrid + rerank** | 0.773 | 0.545 | **0.779** | **0.939** | 2,572 |
| 5 | + section expand | 0.727 | 0.545 | 0.691 | 0.780 | 152 |
| 6 | + graph expand | 0.773 | 0.545 | 0.715 | 0.803 | 160 |
| 7 | + both expands | 0.727 | 0.545 | 0.691 | 0.780 | 143 |

### `contradiction_1c` — 2 questions (n is 2; directional only)

| # | Config | recall@10 | coverage@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|
| 1 | BM25 only | 1.000 | 1.000 | 0.644 | 0.550 |
| 2 | Dense only | 1.000 | 1.000 | 0.566 | 0.417 |
| 3 | Hybrid RRF | 0.500 | 0.500 | 0.500 | 0.500 |
| 4 | Hybrid + rerank | 1.000 | 1.000 | 0.431 | 0.250 |
| 5–7 | any expansion | 0.500 | 0.500 | 0.500 | 0.500 |

### `paraphrase` — 19 re-askings of questions we already know the answers to

| # | Config | recall@10 | coverage@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|
| 1 | BM25 only | 0.561 | 0.263 | 0.496 | 0.595 |
| 3 | Hybrid RRF | 0.553 | 0.263 | 0.527 | 0.695 |
| 4 | Hybrid + rerank | 0.517 | 0.210 | 0.507 | 0.693 |
| 5 | + section expand | 0.474 | 0.158 | 0.491 | 0.684 |
| 6 | **+ graph expand** | **0.693** | **0.474** | **0.600** | 0.695 |
| 7 | + both expands | 0.614 | 0.368 | 0.569 | 0.684 |

`unanswerable` and `adversarial` carry no gold documents by construction — they score
refusal behaviour, not retrieval, and are named rather than reported as zeros.

---

## What the numbers say

### 1. Graph expansion is the single biggest win in the project

**`coverage@10` on multi-hop: 0.429 → 0.714. Recall: 0.714 → 0.905. Cost: 20 ms.**

Three of seven 1B questions had all their evidence in the top 10 before; five do now.

The mechanism is the reason the graph exists. A 1B question names one entity and needs a
second document that often does not contain the question's subject in any form either
retriever scores highly — "who won the War of Drowned Light, and who is in that faction"
retrieves the war's article, and the answer lives in the faction's. Walking one edge
reaches it deterministically, and the hop chain is quotable in the answer.

For comparison, the cross-encoder costs **2,463 ms** and makes this suite *worse*. Graph
expansion costs **20 ms** and is the best row in the table. That is the ordering to defend
when asked why a graph rather than a bigger reranker.

### 2. Reranking helps 1A and harms 1B — still true, and no longer the only option

| | 1A nDCG | 1A MRR | 1B recall | 1B coverage |
|---|---|---|---|---|
| Hybrid RRF | 0.715 | 0.803 | 0.714 | 0.429 |
| Hybrid + rerank | **0.779** | **0.939** | 0.500 | 0.143 |
| Hybrid + graph expand | 0.715 | 0.803 | **0.905** | **0.714** |

A cross-encoder scores each document's relevance to the query *independently*. A multi-hop
question needs documents that are individually weak matches and collectively necessary, so
the reranker correctly demotes exactly the evidence the answer requires.
`docs/evaluation.md` §9 asked for this number specifically; this is it.

**Router rule, derived from measurement:** rerank on for figure and single-lookup intents,
off for multi-hop; graph expansion on by default, since it is a large win on 1B and
*exactly neutral* on 1A and 1C.

### 3. Section expansion hurts, and it was always going to

0.429 → 0.286 on 1B; 0.715 → 0.691 nDCG on 1A. The only row in the table that is worse
than doing nothing.

Section expansion can only add chunks from documents the base retrieval already returned,
so under a fixed k it spends slots it cannot repay in coverage — a doc-level metric. That
is not a surprise, it is arithmetic, and the row exists to state the arithmetic with a
number instead of an argument. It is also why rows 5 and 6 are separate: bundled, section
expansion would have inherited the graph's gain.

Row 7 confirms it from the other side — adding section expansion *to* graph expansion
lowers recall (0.905 → 0.881), because the two compete for the same budget.

### 4. Hybrid still beats both of its own components

recall 0.714 against 0.595 (BM25) and 0.476 (dense); coverage 0.429 against 0.143 and
0.000. Dense alone covers **no** multi-hop question. Each retriever fails on what the
other exists for, which is the case for fusing them.

### 5. Paraphrasing costs about 0.29 of coverage, and the graph does not rescue it

On the 1B subset of `paraphrase` (n = 14), against identical gold documents:

| | original wording | paraphrased |
|---|---|---|
| Hybrid RRF | 0.429 | 0.143 |
| + graph expand | 0.714 | 0.429 |

Graph expansion recovers roughly the same amount either way — it just starts lower. 1A is
untouched (0.600 both ways): a plate lookup does not care how the question is worded.

By style, under graph expansion: colloquial 5/9, formal 2/3, terse 2/5, **oblique 0/2**.

The oblique failures are the useful part, and the suite predicted them. Those two questions
deliberately name no canonical entity ("the great worm of the marrow-fens"), so graph
expansion finds no seed and contributes nothing — the question falls back to base
retrieval, which was already failing it.

**Consequence: A1's normalisation is load-bearing, not cosmetic.** Multi-hop strength
depends on the question naming an entity we can match exactly. Turning a paraphrase into a
canonical name is worth real effort — against the published vocabulary only, never fuzzily
(Finding 13).

### 6. More graph edges made retrieval *worse*, and the fix is not what I expected

LLM extraction added 193 edges from novels and records (`src/graph/extract.py`), taking
the graph from 379 to 572 relations. Re-running row 6:

| graph | 1B recall@10 | 1B coverage@10 |
|---|---|---|
| 379 wiki edges | **0.905** | **0.714** |
| 572 edges (wiki + extracted) | 0.833 | 0.571 |

Isolated by filtering edges at query time — same code, same index, only the graph
differed — so this is the graph doing it, not a coincidence.

**The edges are not wrong. The budget is.** An expansion slot evicts a base hit, and with
wiki edges alone part of the budget went unspent. The extracted edges filled those slots
with tier-3 novel chunks, which displaced gold documents the base retriever had already
found. More edges is not better under a fixed budget; better edges first is.

Two fixes were tried before measuring properly, and neither moved the number: sorting
candidates by confidence, then deduplicating after sorting instead of before. Both were
kept — deduplicating first really did let a 0.6-confidence duplicate shadow the
authoritative edge for the same triple — but neither was this bug. Worth recording,
because the reflex on seeing a regression was to reorder something rather than to isolate
the variable.

The actual fix is `MIN_EXPANSION_CONFIDENCE = 1.0`: only deterministic wiki edges may
spend a slot. The extracted edges stay in the graph, where `/v1/graph/neighbors` and
`/paths` use them to answer and to render hop chains. They are excluded from *retrieval*,
where their cost is measured and their benefit is not.

### 7. `coverage@k` earns its place

On 1B, BM25's recall@10 of 0.595 sounds survivable. Its `coverage@10` of **0.143** says one
question in seven actually has all its evidence present. Same run, same numbers. Reporting
recall alone would have hidden the problem the graph layer was built to solve — and would
then have hidden the fix working.

---

## What is still missing from this table

| Row | Status |
|---|---|
| 8. + conflict layer | A4 exists; needs the answer path to consume it (P2) |
| 9. chunk 300 / 450 / 600 | running — `scripts/chunk_sweep.py`, into `docs/reports/chunk-sweep.json` |
| agentic loop (1C) | P2's orchestrator |

LLM extraction has covered 200 of the 849 candidate narrative passages so far. Extending
it grows the graph, but §6 is the reason that does not automatically grow these numbers.

---

## Reproducing

```bash
uv run python -m eval.runner --suite all --ablation --out docs/reports/ablation-retrieval.json
uv run python -m eval.runner --suite multihop_1b --ablation --failures
uv run python -m eval.runner --suite all --ablation --gate     # fails on any drop
```

The harness refuses to score a configuration whose index is empty. An earlier run of this
table reported dense@10 = 0.000 across every suite because `QDRANT_URL` pointed at a
service the vectors had not been built into, and an absent collection returns `[]` rather
than raising — so the run completed and printed a table of zeros. That guard exists
because of it.
