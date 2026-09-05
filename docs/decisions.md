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

**Status:** proposed, **spike not yet run** · 2026-09-05

**Context.** 11 of 20 dev questions are 1A and the answers exist only in the 85 PNGs.
Roughly 55 `atmo_*` images yield literally zero OCR characters. `plate_01` is a planted
trap: a bar chart with 800 / 2,400 / 6,000 reference values and 1,114 as the real
Emberdeep figure, which Tesseract renders as "Ee". Flat OCR plus an LLM answers 6,000.

Verified by direct inspection on 2026-09-05: the 1,114 bar is drawn **shorter** than the
6,000 reference bar, so "pick the largest number" and "pick the longest bar" both fail.
The requirement is figure *understanding* — binding each value to its label — not figure
text extraction.

**Options.** (a) VLM structured description; (b) OCR plus bounding-box spatial layout,
feeding the model `label@(x,y) = value@(x,y)` pairs; (c) OCR only, accept the loss.

**Proposed decision.** (a), with (b) as the fallback if no free vision model can bind a
chart value to its label. `spikes/vlm_plate_spike.py` is written and armed to decide
this; it asserts Emberdeep → 1,114, Greyfell → 3,695, and Ignatz → a scroll.

**BLOCKED:** no provider credentials are configured yet. Run the spike and record the
result — pass or fail — before writing any image pipeline code.

**TODO(human):** the measured outcome, the model that won, and what we rejected and why.

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
