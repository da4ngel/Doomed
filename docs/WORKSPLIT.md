# Work split — two builders, one seam

> **P2's operational plan is `docs/P2-HANDBOOK.md`.** This file is the boundary; that
> file is the day-by-day work.

**Written 6 Sep (D2).** Freeze **Wed 9 Sep 12:00**, submit **20:00**. Three and a half
working days.

## The seam

```
        P1 — Eyaas (Claude Code)          │          P2 — second builder (Codex)
   everything that PRODUCES evidence      │     everything that CONSUMES evidence
                                          │
  ingestion · images · graph · retrieval  │   agents A1-A6 · orchestrator · answer
  conflicts · eval harness · metrics      │   packet · /v1/chat · UI · CI
                                          │
                    ────────► POST /v1/search ◄────────
                         FROZEN. Live. 56 Postman
                         assertions passing against it.
```

**Nobody edits across the line.** The knowledge layer is finished and tested, so P2 never
has to wait for it, and P1 never breaks P2 by touching agent code.

`src/agents/` and `src/synthesis/` are **empty directories today** — P2 starts on a clean
surface with nothing to merge around.

---

## P2 — the second builder (Codex)

### Why this half

The six agent specs are **already written** in `skills/a1-query-analyst.md` …
`a6-verifier.md` (451 lines). Each has an objective, input schema, output schema, ordered
steps, stop rules and failure fallbacks. You are implementing from a specification against
a frozen, tested interface — the best possible shape for someone joining mid-project.

### Owns, exclusively

| Path | What |
|---|---|
| `src/agents/` | A1 Analyst, A3 Critic, A5 Composer, A6 Verifier, orchestrator, router |
| `src/synthesis/` | `composer.py`, `claims.py`, `citations.py`, `prompts/` |
| `src/api/routes/chat.py` | `POST /v1/chat` returning the answer packet |
| `ui/` | single-file page: inline `[FIG:id]` figures, citation chips, live trace |
| `.github/workflows/ci.yml` | lint, tests, Newman |
| `src/core/trace.py` `usage.py` | interface fixed by P1, yours to extend |
| **Delivery (D5)** | report, video, diagrams, README, `ai_usage/` export |
| Postman folders `04`–`08` | chat, router, edge cases |

### Reads but never edits

- `src/api/schemas.py` — **FROZEN.** `AnswerPacket`, `Claim`, `Citation`, `Visual` are
  already defined. Build to them. A change needs an ADR and both builders.
- `src/retrieval/`, `src/indexing/`, `src/graph/`, `src/ingestion/` — call the API, do
  not reach inside.

### The three things that carry the marks

1. **A5 Composer must emit `claims[]` with per-claim `citation_ids`.** Groundedness is
   computed from it — `count(support != "inferred") / count(claims)`. It cannot be
   retrofitted; if the composer returns prose without claims, that metric is 0 forever.
2. **A5 places `[FIG:asset_id]` markers inline**, at the claim the figure supports, not
   at the end. `GET /v1/assets/{id}` serves the image; `/meta` gives the label→value
   pairs. That is sub-track 1A's entire mechanic.
3. **A3 Sufficiency Critic is sub-track 1C.** Its test: `next_query` must contain a term
   that first appeared in the *previous* step's results. That is what separates reasoning
   from rephrasing, and it is what `gain_per_step` measures.

### Non-negotiable, from CLAUDE.md

- **Retrieved text enters the prompt inside a delimited evidence block, never in the
  instruction position.** The corpus contains in-world orders, decrees and trial
  transcripts — text shaped like instructions. Log matches and emit the
  `instruction_like_text_in_source` warning.
- **Every LLM call goes through `src/core/llm.py`**, which already wraps retry, caching
  and the provider fallback chain. Do not call a provider directly.
- **Compose only from retrieved evidence.** The world is invented; anything the model
  "knows" about the Ashen Era is hallucinated by definition.

---

## P1 — Eyaas (Claude Code)

### Owns, exclusively

| Path | What |
|---|---|
| `eval/` | metrics, suite runner, ablation harness, failure taxonomy |
| `src/graph/extract.py` | LLM entity extraction over `chronicles/` + `ephemera/` |
| `src/synthesis/conflicts.py` | A4 conflict detection — **the one file inside P2's folder that P1 owns** |
| `src/ingestion/` | OCR backfill for the 15 scan-only documents |
| `docs/` | architecture, evaluation, limitations, corpus findings |
| **Evidence (D5)** | the ablation table and every number in it |

### Why A4 sits on this side

Conflict detection is evidence *merging*, not answer *composing*: it clusters claims by
(entity, attribute), resolves by authority tier with corroboration as tiebreak, and emits
`conflicts[]`. It needs the tier table and the graph, both of which live here.

It is also **load-bearing for 1A, not only 1C** (findings addendum, Finding 7): `1a_004`
asks the Thrice-Bound Edge's attunement cost — the tier-1 plate says **94**, the tier-2
wiki asserts "no attunement cost" six times, and the wiki outranks the plate on dense
similarity. Without tier resolution that question returns a fluent, well-cited, wrong
answer.

**Interface P2 codes against:** `detect_conflicts(chunks) -> list[Conflict]`. `Conflict`
is already in the frozen schema. P2 renders whatever it returns.

---

## Sequencing — who is blocked on whom

Nobody, after the first hour.

| Day | P1 | P2 |
|---|---|---|
| **D2 (today)** | eval harness: recall@k, coverage@k, first ablation rows | setup, read specs, A1 Analyst + A5 Composer skeleton |
| **D3 Mon** | LLM graph extraction; A4 conflicts; gold set for 1B/1C | A3 Critic + orchestrator loop; **Mode A answering with real figures** |
| **D4 Tue** | full ablation table; failure taxonomy; OCR backfill | router, A6 Verifier, `missing_information`, UI, CI |
| **D5 Wed** | evaluation.md, limitations.md, ablation table | **report, diagrams, video**, clean-clone check, Postman green |

P2 can build the entire answer path against `/v1/search` **before** A4 conflicts exist —
just render `conflicts: []` until the function lands, then render what it returns.

---

## Rules that stop us breaking each other

1. **Feature branches, PR, reviewed by the other builder, merged without squashing.**
   The rubric assesses this directly.
2. **`src/api/schemas.py` is frozen.** Additive new models are fine (I added
   `GraphNeighborsRequest` etc. that way). Changing `Claim`, `Citation`, `AnswerPacket`,
   `Block`, `Chunk` is an ADR and both builders.
3. **`src/api/main.py` is a shared file** — the only one. P2 adds the chat router there;
   P1 adds nothing further. Keep edits to one line each.
4. **Conventional commits, one logical change each.** Never `git add .` on a day's work.
5. **`data/` is gitignored** — corpus, index and the 65MB of model weights. Do not
   force-add anything under it.

---

## P2's first 30 minutes

```bash
git clone <repo> && cd DOOMED
uv sync --all-groups
cp .env.example .env                       # add OPENROUTER_API_KEY / OPENAI_API_KEY
python -c "import zipfile; zipfile.ZipFile('data/corpus/Ashen_Era_Archive.zip').extractall('data/corpus')"

docker compose up -d qdrant

uv run python -m src.ingestion.pipeline    # ~20s
uv run python -m src.ingestion.images      # ~3 min, cached after
uv run python -m src.graph.store --build   # ~2s
uv run python -m src.ingestion.chunker     # ~10s
uv run python -m src.indexing.build        # ~20 min - start it, then read the specs

uv run uvicorn src.api.main:app --port 8000
```

**Read in this order while the index builds:**

1. `CLAUDE.md` — the non-negotiables
2. `src/api/schemas.py` — the frozen contracts you are building to
3. `skills/a5-answer-composer.md` and `a3-sufficiency-critic.md` — your two hardest agents
4. `docs/corpus-findings-addendum.md` — the seven traps the corpus plants. Findings 7, 8
   and 13 will decide whether your answers are right or confidently wrong.

**Then confirm the seam works for you:**

```bash
curl -s -X POST localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query":"Greyfell Citadel recorded garrison strength","k":3}'
```

Top hit must be `plate_09_location_greyfell_citadel.png`. That answer (**3,695**) appears
in no document in the archive — only in the image. If you see it, the whole knowledge
layer is working for you.

---

## What already exists, so nobody rebuilds it

- **236 documents → 3,134 blocks → 2,474 chunks**, zero dead-letter
- **70 images described**, gold recovery **11/11** on the 1A dev questions
- **198 entities, 742 relations**, all three 1B hop chains resolving with evidence
- **Hybrid retrieval** — dense + BM25 + RRF + rerank, 1.1s warm, tier filtering
- **9 endpoints**, **56 Postman assertions passing**, **188 unit tests**
- **8 ADRs** in `docs/decisions.md` (six carry `TODO(human)` blocks — those are for us,
  not for a model, and the rubric reads them)
