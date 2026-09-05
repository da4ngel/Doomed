# Decision Record

Architecture Decision Records for the Ashen Era Archive Assistant.

**How to read this file.** Each ADR records Context, the options considered, what the AI
proposed, **what we rejected and why**, the decision, and its consequences. The
"rejected and why" block is written by a human — a generated rationale reads as one-shot
generation and is worth less than none. Blocks marked `TODO(human)` are waiting on that
and must be filled before submission.

---

## ADR-000 — 1B is the spine, 1C is its loop, 1A is its renderer

**Status:** accepted · 2026-09-04

**Context.** The challenge offers three sub-tracks and warns that a strong single
sub-track beats a shallow attempt at several. A menu of three features reads as three
half-products; a hierarchy reads as one product.

**Decision.** One evidence-first reasoning engine. Multi-hop retrieval (1B) is the
technical spine; the sufficiency loop (1C) is how that spine decides it has enough; rich
answers (1A) are how it presents what it found.

**Consequences.** Every component is justified by its place in that single pipeline. The
framing sentence is reused verbatim in the report, the video and judge conversations.

**Amendment, 2026-09-05.** The corpus profile inverts the *effort* split without changing
the thesis: 11 of 20 dev questions are 1A, and their answers exist only inside images. 1A
is still the renderer, but it is the renderer that carries most of the marks.

**TODO(human):** what we rejected and why — the case for making 1A the spine instead.

---

## ADR-001 — No orchestration framework

**Status:** accepted · 2026-09-04

**Context.** LangChain or LlamaIndex would save time on day one. The final round requires
every member to explain, justify and modify any part of the system on demand.

**Decision.** Write the orchestration ourselves. No LangChain, no LlamaIndex.

**Consequences.** More code to write; all of it defensible. RRF is fifteen lines we can
explain. Framework internals are not.

**TODO(human):** what we rejected and why — the honest cost of this choice in hours lost.

---

## ADR-002 — Vision model for figure understanding

**Status:** **accepted** · 2026-09-05 · spike run, result below

**Context.** 11 of 20 dev questions are 1A and the answers exist only in the 85 PNGs.
Roughly 55 `atmo_*` images yield literally zero OCR characters. `plate_01` is a planted
trap: a bar chart with 800 / 2,400 / 6,000 reference values and 1,114 as the real
Emberdeep figure, which Tesseract renders as "Ee". Flat OCR plus an LLM answers 6,000.
Verified by direct inspection: the 1,114 bar is drawn **shorter** than the 6,000 bar, so
"largest number" and "longest bar" both fail. The requirement is figure *understanding* —
binding each value to its label — not figure text extraction.

**Options.** (a) VLM structured description; (b) OCR plus bounding-box spatial layout,
feeding `label@(x,y) = value@(x,y)` pairs; (c) OCR only, accept the loss.

**Decision.** (a). Measured, not assumed.

### Spike result — `minimax/minimax-m3:free` via OpenRouter, 2026-09-05

| Case | Expected | Result |
|---|---|---|
| `plate_01` Emberdeep (the trap) | 1,114 | **PASS** — 1,284 in / 270 out, 5,643 ms |
| `plate_09` Greyfell Citadel | 3,695 | **PASS** — 1,284 in / 179 out, 3,457 ms |
| `atmo_portrait` Ignatz Ashgrove | a scroll | **PASS** — 1,723 in / 235 out, 10,014 ms |

Cost: **$0.00** — the whole ladder stayed on the free tier.

The trap is defeated by structure, not luck. The model returned every bar bound to its
own label and marked which one is the subject:

```json
[{"label": "Old Imperial minimum",  "value": "800"},
 {"label": "Border-march standard", "value": "2,400"},
 {"label": "Great Keep standard",   "value": "6,000"},
 {"label": "Emberdeep",             "value": "1,114"}]
```

That is why the prompt demands `values[]` as label/value pairs rather than prose. A prose
description of this plate would contain all four numbers with nothing distinguishing the
answer from the reference bars, and the composer would pick wrong.

### What the first run cost us, honestly

The spike failed three times before producing this. Each failure was a real defect:

1. **Every hardcoded model id had been retired.** `qwen2.5-vl-72b`,
   `llama-3.2-90b-vision` and `gemma-3-27b` all 404 on OpenRouter now. Fixed by adding
   `--discover`, which re-derives the free vision tier from the live catalogue instead of
   trusting a list that silently rots.
2. **The circuit breaker was keyed on the provider alone.** One retired model id opened
   the circuit for OpenRouter entirely, so the escalation ladder never ran — every later
   model reported "circuit open, not attempted". Now keyed on provider **and** model.
3. **A non-retryable 4xx was tripping the breaker.** A 404 for a bad model id is *our*
   bug, not the provider being unhealthy. Tripping on it disables a provider that is
   perfectly fine. `call_with_retry` no longer records a breaker failure for errors it
   will not retry.

A fourth issue was masked by all three: `raise_for_status()` discarded the response body,
so "404 Not Found" was all we saw. The body said "model not found" the whole time. Errors
now carry the provider's own explanation.

**Consequence for the design.** The fallback chain earned its place on first contact: in
the successful run, `google/gemma-4-31b-it:free` returned 429 ("rate-limited upstream"),
the ladder escalated, and the next model answered. That is precisely the demo-day failure
the chain exists for, and it is worth showing on video rather than describing.

**TODO(human):** whether to spend a few dollars on `gpt-4o` for the final index run to
reduce variance, given the free tier already passes all three cases.

---

## ADR-003 — Authority tiers assigned directory-first

**Status:** accepted · 2026-09-05 · implemented in `src/ingestion/tiers.py`

**Context.** Tier drives A4 conflict resolution. The original filename-pattern rules left
**87 of 340 files unclassified**, and an unclassified file defaults to a tier it did not
earn. A confidently mis-resolved conflict is a fabrication with a citation attached,
which is strictly worse than surfacing a disagreement as unresolved.

**Decision.** Directory first, filename second. The folder a curator deliberately placed a
file in is a stronger provenance signal than its name.

**Measured consequence.** Zero unclassified files across the real archive. Distribution
36 / 150 / 8 / 113 / 32, matching the prediction in `corpus-findings.md` Finding 5
exactly. (Sums to 339, not 340: `README.txt` is metadata about the archive rather than
in-world content, so ingestion skips it alongside `sample_questions.json`.)

**Open judgment call.** The wiki is a *fan* wiki placed at tier 2, above the novels at
tier 3 — yet the novels are primary canon and the wiki is secondary commentary on them.
We kept the wiki higher because it is the corpus's structured reference layer while the
novels are narrative prose, but the argument genuinely runs both ways.

**TODO(human):** settle tier 2 vs tier 3 and write the reasoning. This is exactly the
kind of epistemic judgment the rubric rewards, and it must be our words.

---

## ADR-004 — Local-first embeddings and reranking

**Status:** accepted · 2026-09-05

**Context.** The master plan assumed Voyage `voyage-4-large` plus `rerank-2.5` on the free
tier. We have no Voyage key; available providers are OpenRouter, Gemini and AWS Bedrock,
none of which offers a drop-in equivalent that a judge could run without credentials.

**Decision.** `fastembed` BGE-small-en-v1.5 on CPU as the default embedder, behind an
`Embedder` protocol with a `BedrockEmbedder` alternate. Local cross-encoder for reranking.

**Consequences.**
- A judge reproduces retrieval from a clean clone with **no credentials at all**, which
  strengthens the reproducibility path the rubric asks for literally.
- Index cost drops to zero, so re-indexing stays free — the property the corpus profile
  said should never constrain a design decision.
- "Local dense vs Bedrock dense" replaces "voyage-lite vs voyage-large" as an ablation
  row, and is arguably a more interesting comparison.
- Retrieval quality on rare invented proper nouns leans harder on BM25. Finding 13 gives
  a concrete measurable case: separating `greyfell_citadel` from `ironfell_citadel`.

**TODO(human):** what we rejected and why — including whether to buy a Voyage key.

---

## ADR-005 — Deterministic wiki graph before any LLM extraction

**Status:** accepted · 2026-09-05 · implemented in `src/graph/wiki_extract.py`

**Context.** The master plan scheduled LLM entity extraction across all 1,277 pages as a
D3 task — the longest pole in the project. Finding 3 showed the wiki already carries the
graph in Infobox tables and `[[wikilinks]]`.

**Decision.** Parse the skeleton deterministically from the 95 wiki articles first. Use
LLM extraction only for `chronicles/` and `ephemera/`, where relations are genuinely prose.

**Measured consequence.** 203 entities and 379 relations across all 14 predicates, at zero
LLM cost and zero hallucination risk. Every edge cites the infobox row or prose sentence
it came from. All three dev 1B chains resolve end to end.

**What the evidence changed about the implementation.** Testing against the real dev
questions rather than a sample article exposed three defects a smoke test would have
missed: `Victor` on an event article points from the winner (forward direction returned
nothing for 1b_006 while the graph still looked fully populated); entities referenced
before their own article was parsed froze as untyped placeholders, leaving `Faction` at
zero; and six articles carry no infobox at all, with the Cinder-Wrought Aegis stating its
housing only in prose — hop 2 of 1b_003.

**Consequence for the report.** A deterministic graph is far easier to defend than an
LLM-extracted one. Field coverage is reported as a number (currently 100% of relational
infobox rows) rather than asserted.

**TODO(human):** what we rejected and why — notably, whether prose pattern-matching is a
slippery slope back toward hand-written extraction rules.

---

## ADR-006 — Single-file UI instead of Vite + React

**Status:** proposed · 2026-09-05

**Context.** The master plan specifies Vite + React + Tailwind. The build is currently
one person until a second joins, against a hard deadline of 9 Sep 23:30.

**Decision.** A single-file vanilla-JS page served by FastAPI, rendering `[FIG:id]` inline
figures, citation chips and the live trace panel. No build step, no `node_modules`.

**Consequences.** 1A still demos properly, which is what the marks depend on. The
evidence-graph visualisation stays cut-line #2. A judge runs the UI with no npm install.

**TODO(human):** confirm or overturn once the second builder joins.

---

## ADR-007 — Qdrant as a Docker service, with an embedded fallback in one code path

**Status:** accepted · 2026-09-06 · implemented in `src/indexing/qdrant_store.py`

**Context.** The vector store had to be chosen with Docker Desktop switched off on the
build machine. Embedded Qdrant was verified working first (insert, query, and
`authority_tier` payload filtering all pass with no daemon), so both options were live.

**Options.** (a) Docker service; (b) embedded file; (c) no vector DB, brute-force numpy
over ~2,400 × 384 floats, which at this scale is genuinely instant.

**Decision.** (a) Docker service via `QDRANT_URL`, with (b) as the fallback when that
variable is unset — **one class, one code path, chosen by config**. The team runs the
service; the test suite and CI use the embedded file so neither needs a running daemon.

**What decided it in practice.** Embedded Qdrant is single-process. During development an
index build held the lock and a second process could not open the store — `Device or
resource busy` — and a stale builder had to be killed before work could continue. On demo
day, with the API running and an index rebuild wanted, that is a deadlock. The service
removes it. This is the concrete argument, not a theoretical preference for "production
parity".

**Consequences.** Docker Desktop must be running for ingestion and the demo, which is a
real operational cost and is stated in the README. `/v1/ready` reports which backend is
live, and `QdrantUnavailableError` names the fix rather than surfacing a connection trace.

**TODO(human):** what we rejected and why — in particular whether option (c) would have
been the more defensible choice at 2,400 chunks, given "no framework" is our stated
principle elsewhere.

---

## ADR-008 — Chunk size is set by the embedding model's context window

**Status:** accepted · 2026-09-06 · implemented in `src/ingestion/chunker.py`

**Context.** The master plan specified ~600-token chunks. That number was chosen as a
round figure, before an embedding model had been selected.

**The measurement that changed it.** `BAAI/bge-small-en-v1.5` truncates input at **512
tokens**. With a 600-token target, **173 chunks (8.8%) exceeded the window** — their tails
were stored in `chunks.jsonl` and returned by BM25, but never embedded. Text present in
the index yet unreachable by dense retrieval, with no error and no symptom: recall would
simply have been lower than it should be, and nothing would have said why.

**Decision.** `TARGET_TOKENS = 450`, derived as *model context (512) minus room for the
overlap the chunker prepends*. `EMBED_CONTEXT_TOKENS` is a named constant so the
relationship is explicit rather than folklore.

**Measured consequence.** Chunks over the window fell from 173 to **1**, and that one is
an atomic table kept whole by rule 1 — a stated trade-off rather than a leak.

**Consequence for the ablation.** The chunk-size sweep becomes 300 / 450 / 600, and the
600 row now has a known mechanism for any loss it shows rather than being a mystery. A
larger-context embedder would move this number; that is the point of deriving it.

**TODO(human):** what we rejected and why — including whether to switch to an embedder
with a 8k window and drop the constraint entirely.
