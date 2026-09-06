# Decision Record

Architecture Decision Records for the Ashen Era Archive Assistant.

> **DRAFT NOTICE.** The "rejected and why" blocks below are marked `DRAFT - review`.
> They were drafted from this project's own measured evidence and record real
> decisions and real numbers, but the judgement in them must be read, agreed with or
> overruled, and put into our own words before submission. A rationale we have not
> actually endorsed is not collaboration evidence, whatever it says.

> **DRAFT NOTICE.** The "rejected and why" blocks below are marked `DRAFT - review`.
> They were drafted from this project's own measured evidence and record real
> decisions and real numbers, but the judgement in them must be read, agreed with or
> overruled, and put into our own words before submission. A rationale we have not
> actually endorsed is not collaboration evidence, whatever it says.

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

**DRAFT - review.** *What we rejected and why.* We considered making **1A the spine**,
and on the raw numbers it is defensible: 11 of the 20 dev questions are 1A and their
answers exist only inside images, so 1A carries more marks than 1B and 1C combined. We
rejected it because a spine is the thing other parts hang from, and 1A does not connect
anything - a figure pipeline is a leaf. Sub-track 1B is what forces an entity graph,
evidence bundling and hop chains into existence; once those exist, 1C is the loop over
them and 1A is the renderer at the end. Choosing 1A as the spine would have produced an
excellent figure reader and no reason to build a graph at all.

The honest counter, which we accept: our *effort* profile does not match our thesis. We
spent the first full working day on the image pipeline, because that is where the marks
are. We would say the thesis describes the architecture and the effort describes the
scoreboard, and that both are true.

---

## ADR-001 — No orchestration framework

**Status:** accepted · 2026-09-04

**Context.** LangChain or LlamaIndex would save time on day one. The final round requires
every member to explain, justify and modify any part of the system on demand.

**Decision.** Write the orchestration ourselves. No LangChain, no LlamaIndex.

**Consequences.** More code to write; all of it defensible. RRF is fifteen lines we can
explain. Framework internals are not.

**DRAFT - review.** *What we rejected and why.* We rejected LangChain and LlamaIndex,
and the cost was real rather than theoretical - roughly a day across the project. RRF,
the hybrid retriever, the Qdrant wrapper, the provider fallback chain and the retry/cache
layer are all code a framework would have supplied. We also shipped bugs a framework
would not have had: chunk ids that collided, Qdrant point ids that overwrote each other
batch by batch, an entity split between "The Iron-Ring Cartel" and "Iron-Ring Cartel".

We would make the same choice again, for one reason that outweighs the day: **we found
those bugs.** Every one surfaced because we could read the code that produced the number.
The Qdrant id collision silently indexed 2,444 chunks as 256 vectors while reporting
success - inside a framework that is a mysteriously weak recall score with nowhere to
look. The final round requires every member to explain and modify any part on demand, and
we can defend 400 lines we wrote in a way nobody defends a dependency.

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

**DRAFT - review.** *Whether to pay for the final index run.* We decided **not to**.
`minimax/minimax-m3:free` recovers **11 of 11** gold answers across the whole 1A set, not
just the three spike cases - measured after describing all 70 images. Paying for `gpt-4o`
would buy variance reduction on a metric already at 100%, and would cost us the stronger
claim: that the figure pipeline runs at **$0.00** and a judge can reproduce it on a free
key. The paid rungs stay in the ladder as a fallback if the free tier is throttled during
the final run, and `fallback_used` records it in the usage row if that happens.

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

**DRAFT - review.** *Settling tier 2 vs tier 3.* We keep the **wiki at tier 2, above the
novels at tier 3**. The reasoning is about what each source is *for*, not which is more
canonical.

The novels are primary canon and the wiki is secondary commentary on them, which argues
for reversing the order. We reject that because authority tiers answer one narrow
question - *when two sources disagree about a fact, which do we believe?* - and on that
question the wiki is better evidence. It states facts as structured assertions
(`| Garrison strength | 2598 |`) that are directly comparable; the novels state them
inside narrative, where a character may be lying, mistaken, or speaking figuratively. A
tier is a claim about *reliability of assertion*, not about *canonicity of the work*.

Two pieces of corpus evidence support this. The wiki annotates its own uncertainty -
`gloamreach.md` records "Founded | Contested; consult the Annals and Codex" rather than
inventing a year, which is exactly the behaviour a higher tier should show. And the
corpus README warns that in-world authors "are not always reliable", a warning aimed at
the narrative and ephemeral material rather than at the reference layer.

We accept this is arguable and that a reader could reasonably order it the other way. It
does not affect either 1C answer, since both resolve to tier 1.

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

**DRAFT - review.** *What we rejected and why.* We rejected buying a Voyage key, which
would have given better embeddings and matched the original plan. Two reasons.

First, reproducibility. With local embeddings a judge clones the repo and gets working
retrieval with **no credentials at all**, and the rubric asks for exactly that path. A
Voyage key would have made our headline result unreproducible by the people marking it.

Second, the measured gap is smaller here than it would be on a normal corpus, because
this archive is invented proper nouns where BM25 does much of the work - `greyfell`
versus `ironfell` is a lexical problem, not a semantic one, and a better embedder does
not help with it.

What we gave up: BGE-small truncates at 512 tokens, which forced our chunk size down, and
a full re-index costs about 20 minutes on CPU. We consider that a fair trade for a system
anyone can run.

---

## ADR-005 — Deterministic wiki graph before any LLM extraction

**Status:** accepted · 2026-09-05 · implemented in `src/graph/wiki_extract.py`

**Context.** The master plan scheduled LLM entity extraction across all 1,277 pages as a
D3 task — the longest pole in the project. Finding 3 showed the wiki already carries the
graph in Infobox tables and `[[wikilinks]]`.

**Decision.** Parse the skeleton deterministically from the 95 wiki articles first. Use
LLM extraction only for `chronicles/` and `ephemera/`, where relations are genuinely prose.

**Measured consequence.** 198 entities and 379 deterministic relations across all 14
predicates (572 once LLM-extracted edges are merged), at zero
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

**DRAFT - review.** *What we rejected and why.* The fair challenge is that our prose
patterns are hand-written extraction rules by another name, and that we are one step from
a brittle pile of regexes.

We accept the direction of that criticism, and think the constraint we chose answers it:
**every prose pattern requires a `[[wikilink]]` as its object.** A pattern can therefore
only connect two names the corpus itself wrote down and marked as entities - it can never
invent one. That is a categorical limit rather than a matter of care, which is why we
consider these six patterns different in kind from open-ended rule-writing. They exist
because six wiki articles have no Infobox at all, and one of them holds hop 2 of
`1b_003`.

What we also rejected: running LLM extraction over the wiki as well, for uniformity. A
deterministic edge citing an infobox row survives the question "how do you know this is
real?" in a way a model-extracted edge does not, and the wiki is where most of our graph
lives.

---

## ADR-006 — Single-file UI instead of Vite + React

**Status:** proposed · 2026-09-05

**Context.** The master plan specifies Vite + React + Tailwind. The build is currently
one person until a second joins, against a hard deadline of 9 Sep 23:30.

**Decision.** A single-file vanilla-JS page served by FastAPI, rendering `[FIG:id]` inline
figures, citation chips and the live trace panel. No build step, no `node_modules`.

**Consequences.** 1A still demos properly, which is what the marks depend on. The
evidence-graph visualisation stays cut-line #2. A judge runs the UI with no npm install.

**DRAFT - review.** *Confirmed on 6 Sep, when the second builder joined.* We kept the
single-file UI. With two builders and three and a half days, the second builder's time is
better spent on the six agents than on a React build, and the demo needs the UI to render
inline figures, citation chips and a live trace panel - all of which a single file does.
We revisit only if the trace panel proves unworkable without a component model.

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

**DRAFT - review.** *What we rejected and why.* Option (c), brute-force numpy, is the
choice most consistent with our stated principles, and we came close to taking it. At
2,474 vectors of 384 dimensions the whole matrix is about 3.8 MB and a cosine scan is
sub-millisecond - genuinely faster than a round trip to Qdrant, with zero dependencies
and code any team member could derive on a whiteboard.

We rejected it for one concrete reason: **payload filtering.** `SearchFilters` narrows by
`authority_tier` and `source_type`, those filters are toggled by the ablation table, and
filtering *after* retrieval silently shrinks k - ask for 10 tier-1 chunks, get 3, and the
recall number quietly measures something else. Qdrant applies the filter during search.
Hand-rolling that correctly, with the over-fetching needed to keep k honest, is the part
we did not want to write under deadline.

The honest weakness in our position: we hand-rolled exactly that logic in the BM25 store
anyway, so the argument is about where we chose to spend the risk, not about
capability.

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

**DRAFT - review.** *What we rejected and why.* We rejected switching to a
larger-context embedder, which would have removed the constraint rather than managed it
and let us keep 600-token chunks with no truncation.

We rejected it because the constraint turned out to be *informative*. Deriving chunk size
from the model's context window is a defensible engineering rule; picking 600 because it
is a round number is not, and the 8.8% silent truncation we measured is the evidence. A
larger window would have hidden the mistake rather than corrected the reasoning. There is
also a practical reason: BGE-small is 65 MB and runs on any CPU, and a larger model costs
download size and latency on a corpus where retrieval is already the fast part.

What we would revisit with more time: measuring 300 / 450 / 600 against a larger-context
model as a further ablation row, to separate "600 was too big for BGE-small" from "600 is
too big".

---

## ADR-009 — Context expansion is additive, and it spends the same k budget

**Status:** accepted · 2026-09-07 · implemented in `src/retrieval/expand.py`

**Context.** `coverage@10` on `multihop_1b` is **0.429** under the best retrieval config.
Four of seven multi-hop questions do not have all their gold documents in the top 10, so
they are unanswerable regardless of how good the composer is. Ablation rows 5 and 6 exist
to fix exactly this, and the graph — 198 entities, 379 sourced relations — was built for
it and was not wired into retrieval.

**Decision 1 — two expansions, measured separately.** Section expansion (row 5) pulls the
chunks either side of a hit. Graph expansion (row 6) walks relations out from entities
named in the query and collects the `evidence_chunk_id` that licenses each hop.

They are separate functions with separate ablation rows because they cannot do the same
job: **section expansion can only add chunks from documents the base retrieval already
found, so it is arithmetically incapable of improving `coverage@k`**, which is measured on
document ids. Bundling the two under one flag would let a section-expansion row inherit
credit for a graph-expansion gain.

**Decision 2 — expansion spends the same `k`, it does not extend it.** Up to `k // 2`
slots are reserved for expanded chunks and taken from the *bottom* of the base ranking.
The response still holds `k` hits.

This is the decision most worth defending. The alternative — appending expanded chunks
after the base top-k — cannot lose, and that is precisely what is wrong with it: row 6
would then be scored on 22 chunks against row 3's 10, and the "gain" would be mostly the
extra evidence, not the graph. Reserving from the same budget makes it a real trade — the
weakest base hits are evicted in favour of graph-reached ones — so a coverage gain is
attributable to the graph and a loss is visible instead of masked.

**Decision 3 — the schema change.** `SearchRequest` and `SearchResponse` are frozen, and
this adds `expand_mode` to the request and `expanded` / `expansion_reasons` to the
response.

Every addition is optional and defaulted, so a request written before this ADR produces
byte-identical behaviour — `expand` already existed and already defaulted to false. The
seam is not renegotiated, only extended. `expansion_reasons` maps each added chunk id to a
one-line justification ("reached via `Purge of Blackport -won-> Iron-Ring Cartel`"),
because a chunk that reached the evidence bundle without a retriever score and without an
explanation is exactly the kind of thing that ends up cited in an answer nobody can
defend.

**Decision 4 — query entity matching stays exact.** Entities are matched against the
vocabulary by verbatim containment under the same article-insensitive rule as
`entity_id()`, longest name first. No fuzzy matching, no edit distance. Finding 13 is the
reason: `greyfell_citadel` (garrison 3,695) and `ironfell_citadel` (1,096) are one edit
apart, and a near-miss here returns a wrong number carrying a real citation. Correcting a
misspelling is A1's job, against the published vocabulary, before the request is made.

Names shorter than four characters are not matched at all — they appear inside ordinary
words and would attach an entity to nearly every question.

**Consequence.** Rows 5 and 6 of the ablation become runnable, and 0.429 is the number
they have to beat. If graph expansion does not beat it, that is a reportable result about
this corpus rather than a reason to change the metric.

**DRAFT - review.** *What we rejected and why.* We rejected expanding by embedding
similarity to the hit — fetching the nearest chunks to each result rather than its graph
neighbours or its section neighbours.

We rejected it because it adds no information. The nearest neighbours of a chunk the dense
retriever already ranked highly are, by construction, chunks the dense retriever nearly
ranked highly — so it deepens the existing result rather than reaching what the retriever
missed, which is the entire failure mode on multi-hop. It is also unexplainable: "this
chunk is similar to another chunk we retrieved" is not a justification a judge can check,
whereas a hop chain is.

We also rejected always walking two hops. Two hops from a hub entity reaches most of the
graph, and the cap would then decide the evidence bundle rather than the question. One hop
answers the shape every dev 1B question actually has ("who won X, and who are they"), and
two remains available per request.

What we would revisit with more time: letting A3 request a second hop only after the first
proves insufficient, which is the sufficiency loop doing its job rather than a fixed depth
guessing in advance.
