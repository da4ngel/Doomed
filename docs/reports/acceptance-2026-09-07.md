# Acceptance run — 20 dev questions, 7 September

Three full acceptance runs against the real corpus on the merged tree, each after a
fix the previous run exposed. Artifacts in
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

---

## Three runs, two fixes, and what each one bought

| run | claims | empty | lexical* | **mean groundedness** | structural errors |
|---|---|---|---|---|---|
| 1 — as handed over | 7 | 15 | 5 | **0.250** | 0 |
| 2 — budgets raised | 13 | 12 | 6 | **0.375** | 0 |
| 3 — entailment fixed | 13 | **7** | **11** | **0.650** | 0 |

\* lexical is a substring check and is **not** a correctness score. It moved because
real answers appeared where there had been none, but it must not be quoted as accuracy.

### Fix 1 — the budgets (run 1 → 2)

Six questions gained claims, including both 1C questions. Zero budget stop reasons
remain in run 2; every `token budget exhausted` and `LLM deadline exceeded` is gone.

### Fix 2 — A6's entailment call was never running (run 2 → 3)

The finding this run existed to produce. OpenAI refuses `response_format:
json_object` unless the literal word "json" appears in the messages. A6's entailment
prompt showed the exact shape it wanted and never said the word, so **every**
entailment call returned 400, the verifier swallowed it as `entailment_skipped`, and
every non-extractive claim was stamped "Inference (not verified)".

It hid behind a literal-substring fast path: an extractive answer like
`Emberdeep: 1,114` matches its excerpt verbatim and never needs an LLM call. That is
why 1A sat at groundedness 1.00 throughout while everything else sat at 0.00, and why
this looked like a strict verifier rather than a broken one.

Mean groundedness went 0.375 → 0.650 on that one fix. Six answers became verified,
including both 1C questions:

```
Gloamreach was founded in 246 AS.   [cite_0c8f83ffa2c999b5]
Sources disagree about Gloamreach founding year: 246 AS (tier 1) versus
286 AS (tier 4). Tier 1 outranks tier 4.
```

No "Inference (not verified)" prefix. The year is answered and the disagreement is
surfaced and resolved by tier - which is the whole 1C requirement.

### What is left, and it is now a real verdict

Four of seven 1B questions still return nothing, and `1b_007` now says:

```
No proposed claim had valid supporting evidence
```

That is A6 **running** and rejecting the claims, not A6 failing to run. A5 composes a
multi-hop claim and its cited excerpts do not support it. Whether the citation binding
is wrong or the claim genuinely overreaches is the open question, and it is the honest
remaining limitation of this system.

Three of the five `1a_v*` variants still fail in retrieval, with gold coverage 0.00 -
unchanged by either fix, because no amount of reasoning recovers evidence that was
never retrieved.

---

## The unanswerable suite — 8 questions

| | result |
|---|---|
| attempted | 8 |
| structural errors | **0** |
| **unverified claims** | **0** — nothing was asserted that A6 had not entailed |
| concrete `missing_information` | **7 of 8** |
| full refusals | 2 (`un_001`, `un_006`) |

**These questions are partially answerable by design.** Each has a component the
corpus records and one it does not, so a blanket refusal would be as wrong as a
fabrication. `un_002` asks for "appearance, origin and powers" of The Silent Psalter:
the infobox gives appearance and origin, and the answer returns them and then says
*"Still unresolved: What are the powers of The Silent Psalter?"* That is the shape the
track is testing for.

`un_005` — "What does Maelis Harrowick the Pale look like?" — is the one packet with
no `missing_information`, and correctly so: it is fully answerable from the portrait
plate, which is an `atmo_*` image that yields **zero OCR characters**. Only the vision
description makes that question answerable at all.

The two full refusals are A6 doing its job rather than the pipeline failing:

```
un_006 -> I could not establish an answer from the retrieved evidence.
          No proposed claim had valid supporting evidence
```

**Refusal accuracy is not computed here.** Whether each refusal was *correct* needs
the same human review as the dev suite. What is measured is that nothing was asserted
without verified support, and that is the property the rubric cares about most.

---

## Two findings from the UI contract check

The browser extension was unavailable here, as it was for P2, so the UI was verified
at the contract level instead: the page is served, `/v1/chat/jobs` returns a trace id,
`/v1/traces/{id}` carries the `packet` the UI reads, and `/v1/assets/{id}` serves the
figure as `image/png`. Visual rendering still needs a human at a browser.

### Every answer reports 0% confidence — known, not fixed

The composer's instruction shows the output shape as
`{claims: [{..., confidence: 0.0}]}` and the model copies `0.0` straight through, so
`packet.confidence` — the mean of its claims — is 0.0 on every answer, including ones
that are fully verified and non-partial. The UI renders `packet.confidence*100`%, so a
correct, entailed, cited answer displays **0%**.

**Fixing the prompt was tried and reverted.** Naming the field without a value and
asking the model to judge it made the flagship Emberdeep answer fail A6 entailment —
1 verified claim became 0. A cosmetic badge is not worth trading a working demo answer
for, so the prompt stands and the display is recorded as a known flaw. The right fix is
probably to derive confidence from support and entailment status in the verifier rather
than trusting the model's self-report, and that is a change to make with an eval behind
it, not hours before a freeze.

### The seam is version-sensitive, which is the argument for merging

Running the chat service from the pre-merge branch against the merged knowledge API
fails every retrieval call with `ValidationError`. `SearchResponse` gained `expanded`
and `expansion_reasons` after the branch forked, and `Frozen` sets `extra="forbid"`, so
the older client rejects every response the newer server sends.

Additive schema changes are safe in one direction only: a **new** client tolerates an
old server, an **old** client does not tolerate a new one. Both halves must ship from
the same commit, which is exactly what the merge delivers.

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
