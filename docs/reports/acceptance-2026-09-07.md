# Acceptance run — 20 dev questions, 7 September

First full acceptance run against the real corpus on the merged tree. Artifacts in
`tests/reasoning/results/2026-09-08/`; the runner's own verdict is
`manual_review_required`, and this document does not overrule it.

**Nothing here is a correctness score.** `lexical_answer_match` is a substring check.
Human review against `docs/evaluation.md` (0–3 per answer) has not been done, and the
numbers below are observed behaviour only.

---

## Configuration

| | |
|---|---|
| Index | 236 documents · 2,474 chunks · 2,474 vectors · 70 described images (16 with OCR) |
| Graph | 198 entities · 742 relations (379 wiki, 363 extracted, gated at confidence 1.0) |
| Synthesis | `gpt-4o-mini` — **not** the documented OpenRouter path, see below |
| Budgets at run time | 25,000 ms · 60,000 tokens (the defaults this run caused us to raise) |

**Why OpenAI and not OpenRouter.** OpenRouter was exhausted in both directions on the
day: the free tier at 0 of 50 requests, and paid credits below the cost of a single
2,400-token completion (`402 … can only afford 1251`). Separately,
`minimax/minimax-m3:free` — the free model the handbook recommends — **no longer
exists**; OpenRouter 404s it as withdrawn in favour of a paid slug. Any report of these
results must say the answers were composed on OpenAI.

---

## What happened

| | count |
|---|---|
| attempted | 20 |
| structural errors | **0** |
| packets with ≥1 claim | 7 |
| empty answers | 15 |
| partial packets | 16 |
| lexical matches *(diagnostic only)* | 5 |

### By track

| track | groundedness | gold coverage | behaviour |
|---|---|---|---|
| 1A plates (6) | **1.00** | **1.00** | 5 of 6 answered, mostly non-partial, ~5 s |
| 1A variants (5) | 0.00 | 0.00 | retrieval recall 0.50 — the gold documents were not found |
| 1B multi-hop (7) | 0.00 | 1.00 on 3 of 7 | reached A5, then stopped on a budget |
| 1C contradiction (2) | 0.00 | **1.00** | conflict resolved correctly, then stopped on a budget |

---

## 1. The planted trap is answered correctly

```
1a_001 →  Emberdeep: 1,114
          [cite_2dd8409c5fb01689] [FIG:img_29ea682914218630]
```

`plate_01_location_emberdeep.png` is a bar chart whose reference bars read 800 / 2,400 /
6,000 while Emberdeep's actual figure is **1,114**. Tesseract, run on this machine at
0.95 confidence, returns 141 characters of labels and **no digits at all** — so a flat
OCR-plus-LLM pipeline has nothing to answer with, or answers 6,000 from the caption.

The vision path recovers all four values and the answer cites the figure. This is the
single clearest justification for ADR-002 in the whole corpus.

## 2. The conflict layer works, and was then cut off

```
1c_000 →  Sources disagree about Gloamreach founding year:
          246 AS (tier 1) versus 286 AS (tier 4). Tier 1 outranks tier 4.
          ...
          Investigation stopped: LLM deadline exceeded
```

A4 detected the conflict, resolved it by tier and rendered the disagreement — the whole
1C answer path — and the run then died before composing. The analysis was right and the
packet was empty.

## 3. Both budgets landed only on 1B and 1C

Observed latencies clustered at 25.5 s, 25.9 s, 26.8 s against a 25,000 ms ceiling.

```
1b_007  Investigation stopped: token budget exhausted
1c_000  Investigation stopped: LLM deadline exceeded
```

1A finishes in ~5 s and one LLM call and never noticed. 1B runs A2/A3 three times and
merges 16–30 chunks. **A budget that only fits the easy half of the corpus is mis-set**,
and 1B is the spine. Raised to 90,000 ms and 200,000 tokens, sized from these numbers.

Two budget defects were fixed on the way here and are not tuning:

- the reservation counted **UTF-8 bytes as tokens**, about 4x over, so a realistic
  prompt reserved 13,315 where it should reserve 5,304 — four affordable calls instead
  of eleven
- `Budget.cancelled` was set on the token path and not the wall-clock path, so what a
  caller observed depended on which limit bit first

## 4. What the budgets were hiding — the real finding

Re-running `1b_007` with budgets far above any ceiling removes both stop reasons, and a
different failure appears:

```
No proposed claim had valid supporting evidence
warnings: claim_downgraded
```

**A5 does compose claims for multi-hop; A6 rejects all of them as not entailed by their
citations.** No budget will fix that. It is consistent with the 8/20 supported-claim
figure recorded before this branch was handed over.

The machinery underneath is working, which is what makes this worth chasing rather than
redesigning: A3 discovered *"The Iron-Ring Cartel is confirmed as the group to which
Ederon Fellgard is a member"*, `graph_neighbors` returned 118 edges, A4 merged 30
distinct chunks. **The chain is found. The claims do not survive verification.**

Whether A6 is correctly strict or wrongly strict is the open question, and it is a
question for human review rather than for a patch that makes the number go up.

## 5. The 1A variant questions fail in retrieval, not reasoning

The five `1a_v*` questions show gold coverage 0.00 and recall 0.50 — the evidence never
reached A5. That is a retrieval result, and it matches the paraphrase finding already
recorded in `limitations.md`: expansion seeds on exact entity matches, so a question
that names nothing we can match falls back to plain hybrid retrieval.

---

## What this run does not establish

- **No correctness score.** Five lexical matches is a substring count. Groundedness of
  1.00 means every claim cited something, not that the answer is right.
- **One run, one model, n = 20.** Composed on `gpt-4o-mini`, not the documented path.
- **The unanswerable suite has not been run**, so refusal accuracy is unmeasured.
- **No browser QA**, so nothing here says the UI renders any of it.
- **Human review is outstanding** and is what turns this into an evaluation.

## Reproducing

```bash
uv run uvicorn src.api.main:app --host 127.0.0.1 --port 8000
LLM_MODEL_SYNTHESIS=gpt-4o-mini KNOWLEDGE_API_URL=http://127.0.0.1:8000 \
  uv run uvicorn src.api.routes.chat:create_app --factory --host 127.0.0.1 --port 8001

uv run python -m tests.reasoning.acceptance --preflight-only --out <run>
uv run python -m tests.reasoning.acceptance --suite dev --out <run>
```

Both services and the runner together need roughly 1.5 GB free; this run's predecessors
were killed twice by the OOM reaper on a 15.3 GB machine with a game holding 4 GB.
