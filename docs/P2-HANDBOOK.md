# P2 handbook — the reasoning layer

**For the second builder, working in Codex.** Written 6 Sep (D2).
Freeze **Wed 9 Sep 12:00**. Submit **20:00**. Three and a half days.

You own the half of the system that turns evidence into answers. The half that produces
evidence is finished, tested, and behind a frozen HTTP interface — so you will never wait
on it, and you will never merge against it.

---

## 1. Orientation (15 minutes)

### What already exists

| | |
|---|---|
| 236 logical documents | format twins collapsed, tiers assigned, zero dead-letter |
| 3,095 blocks · 2,444 chunks | tables kept whole, page + bbox for citations |
| 70 images described | **gold recovery 11/11** on the 1A dev questions |
| 203 entities · 379 relations | every edge citing the infobox row it came from |
| Hybrid retrieval | dense + BM25 + RRF + rerank, 1.1 s warm |
| 202 unit tests · 56 Postman assertions | all green |

### The seam

```
   knowledge layer (P1, done)          POST /v1/search          reasoning layer (you)
   ingestion · images · graph   ─────────► frozen ◄─────────   A1–A6 · /v1/chat · UI
```

You call the API. You never import from `src/ingestion/`, `src/indexing/`,
`src/retrieval/` or `src/graph/`.

### The one command that proves it works for you

```bash
curl -s -X POST localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query":"Greyfell Citadel recorded garrison strength","k":3}'
```

Top hit must be `plate_09_location_greyfell_citadel.png`. That answer — **3,695** —
appears in **no document in the archive**. It exists only as pixels in an image the
knowledge layer described for you. If you see it, everything upstream is working.

---

## 2. Setup (~25 minutes, mostly waiting)

```bash
git clone https://github.com/da4ngel/Doomed.git && cd Doomed
uv sync --all-groups
cp .env.example .env                       # add OPENROUTER_API_KEY
python -c "import zipfile; zipfile.ZipFile('data/corpus/Ashen_Era_Archive.zip').extractall('data/corpus')"

docker compose up -d qdrant

uv run python -m src.ingestion.pipeline    # ~20 s
uv run python -m src.graph.store --build   # ~2 s
uv run python -m src.ingestion.chunker     # ~10 s
uv run python -m src.ingestion.images      # ~3 min
uv run python -m src.indexing.build        # ~20 min  ← START THIS, THEN READ SECTION 3
```

**Read while the index builds**, in this order:

1. `CLAUDE.md` — the non-negotiables. Short.
2. `src/api/schemas.py` — the frozen contracts you build to. `AnswerPacket`, `Claim`,
   `Citation`, `Visual`, `TraceStep`, `UsageRecord` already exist.
3. `skills/a5-answer-composer.md` and `skills/a3-sufficiency-critic.md` — your two
   hardest agents, fully specified.
4. Section 3 below.

Then:

```bash
uv run uvicorn src.api.main:app --port 8000
curl -s localhost:8000/v1/ready       # status: ready, warm: true
```

---

## 3. The three traps that decide whether your answers are right

These are measured properties of the corpus, not hypotheticals. Each one produces an
answer that is **fluent, confident, and carries a real citation** — the failure a reader
cannot catch.

### Trap 1 — the tier-1 plate contradicts the tier-2 wiki (`1a_004`)

> *"According to the figure plate detailing weapon binding, how many shards of will are
> required to attune The Thrice-Bound Edge?"*

| Source | Tier | Says |
|---|---|---|
| `plate_04_artifact_the_thrice_bound_edge.png` | 1 | **94** |
| `wiki/the_thrice_bound_edge.md` | 2 | **"no attunement cost"** — stated six times |

The wiki article is topically perfect for that question and **outranks the plate on dense
similarity**. If your composer takes the top text chunk, it answers "no attunement cost is
recorded", cites a real document, and is wrong.

**What you do:** the answer packet has `conflicts[]` for exactly this. P1's
`detect_conflicts()` resolves by authority tier. Until it lands (D3), render `conflicts: []`
and prefer tier-1 evidence when two chunks disagree on the same attribute.

Also: **"shards of will" appears nowhere in the corpus.** The plate says *vitae-grains*.
A1 must not "correct" an unrecognised unit into something it thinks it recognises.

### Trap 2 — one-token name differences (`1a_004` vs `1a_007`)

`The Thrice-Bound **Edge**` = 94. `The Thrice-Bound **Lantern**` = 55. Retrieve the wrong
plate and the answer is confidently wrong. Worse: **55 is also the "Adept tolerance"
reference bar on the Lantern's own plate**, so a model reading numbers without labels
cannot tell which 55 is the answer.

Use `/v1/assets/{id}/meta` — it returns `values[]` as explicit label→value pairs.

### Trap 3 — near-miss place names (Finding 13)

The 8 locations with a garrison plate and the 17 wiki articles with a `Garrison strength`
row are **disjoint sets**, with decoys between them:

| Asked about (image-only) | Nearest wiki name with a number |
|---|---|
| Greyfell Citadel — 3,695 | Ironfell **Citadel** — 1,096 |
| Embercrag Fortress | Vharen**crag Fortress** — 9,478 |
| Emberdeep — 1,114 | Crookvale — 1,004 |

**Never fuzzy-match an invented proper noun.** `/v1/graph/neighbors` already refuses:
`"Greyfel Citadell"` returns `resolved: false` rather than guessing. A1 must behave the
same way — correct only against the entity vocabulary, show the correction, allow rollback.

---

## 4. What you own

| Path | What |
|---|---|
| `src/agents/` | `analyst.py` (A1), `retriever.py` (A2), `critic.py` (A3), `composer.py` (A5), `verifier.py` (A6), `orchestrator.py`, `router.py` |
| `src/synthesis/` | `claims.py`, `citations.py`, `prompts/` — **except `conflicts.py`, which is P1's** |
| `src/api/routes/chat.py` | `POST /v1/chat`, `GET /v1/traces/{id}` |
| `src/core/trace.py` `usage.py` | written by P1 with the interface fixed; **yours to extend** |
| `ui/` | single-file page |
| `.github/workflows/ci.yml` | lint, tests, Newman |
| Postman folders 04–08 | chat, router, edge cases |
| **Delivery** | report, video, diagrams, `ai_usage/` export |

### Two shared files, one line each

- **`src/api/main.py`** — you add `app.include_router(chat_routes.router)`. P1 adds nothing
  further.
- **`src/api/schemas.py`** — **FROZEN.** Additive new models are fine (P1 added
  `GraphNeighborsRequest` that way). Changing `Claim`, `Citation`, `AnswerPacket`, `Block`
  or `Chunk` needs an ADR and both builders.

Everything else is disjoint by directory. There is no other file both of us touch.

---

## 5. The interfaces you build against

### Retrieval — `POST /v1/search`

```json
{ "query": "...", "mode": "hybrid|dense|sparse", "k": 10, "rerank": true,
  "filters": { "authority_tier": [1,2], "source_type": ["figure_plate"], "doc_id": [] } }
```

Returns `hits[]` with `chunk_id`, `doc_id`, `text`, `score`, `page`, `section_path`,
`source_type`, `authority_tier`, `asset_ids`, and `dense_rank` / `sparse_rank` /
`rerank_score` so you can see which retriever found what.

### Graph — `POST /v1/graph/neighbors` and `/paths`

```json
{ "entity": "The War of Drowned Light", "hops": 2 }
{ "from": "Gravemaw Wyrm", "to": "The Bleeding Crown", "max_hops": 3 }
```

`paths` returns `readable` — `"Gravemaw Wyrm -lair_of-> Marrowwell Abbey | Marrowwell
Abbey -ruled_by-> The Bleeding Crown"` — which is the hop chain your 1B answer quotes to
show its working. Every hop carries `evidence_chunk_id` and `authority_tier`.

Unresolved names return `resolved: false`. Handle that rather than assuming a match.

### Assets — `GET /v1/assets/{id}` and `/meta`

`/meta` gives `values[]` (label→value pairs), `caption`, `entity_link`, `description`.
`[FIG:asset_id]` markers in `answer_markdown` resolve to `/v1/assets/{asset_id}`.

### A2's toolbox — four real tools, not six

`skills/a2-retrieval-agent.md` names six. Four exist today:

| Spec tool | Use |
|---|---|
| `hybrid_search` | `POST /v1/search` |
| `graph_neighbors` | `POST /v1/graph/neighbors` |
| `graph_paths` | `POST /v1/graph/paths` |
| `figure_search` | `POST /v1/search` with `filters.source_type: ["figure_plate","wiki_image"]` |
| `list_mentions` | `POST /v1/search` on the entity name — no new endpoint needed |
| `read_section` | **does not exist.** Ask P1 if A3 actually chooses it; do not stub it |

### LLM calls — `src/core/llm.py`

```python
from src.core.llm import LLMClient
client = LLMClient()
response = client.complete(
    [{"role": "user", "parts": [{"type": "text", "text": prompt}]}],
    model="deepseek/deepseek-chat", provider="openrouter", json_mode=True,
)
payload = response.json_payload()      # tolerates a fenced code block
```

Retry, caching and the provider fallback chain are already wired. **Never call a provider
directly** — CLAUDE.md makes this a hard rule, and the cache is what keeps eval re-runs
free and protects the demo from a 429.

---

## 6. Day by day

| Day | Build | Done when |
|---|---|---|
| **D2 (today)** | setup; read; `analyst.py` (A1); `retriever.py` (A2, four tools) | A1 handles all 20 dev questions without rewriting a proper noun |
| **D3 AM** | `composer.py` (A5), `claims.py`, `citations.py`; `POST /v1/chat` mode=`rich` | **Mode A: a 1A question answers with `[FIG:id]` inline and the figure loads.** Highest-value milestone in your half |
| **D3 PM** | `critic.py` (A3) + `orchestrator.py`, hard budgets, redundancy guard | A 3-hop question runs ≥2 steps, and step 2's query contains a term first seen in step 1's results |
| **D4 AM** | `router.py` (mode=auto), `verifier.py` (A6), `missing_information` | An unanswerable question refuses with non-empty `missing_information[]` and zero `corroborated` claims |
| **D4 PM** | `ui/index.html`; Postman 04–08; CI | UI shows an inline figure and a live trace panel; Newman green |
| **D5 AM** | **freeze 12:00**, then report, diagrams, video | Video recorded 14:00, uploaded 18:30, submit 20:00 |

**You are never blocked on P1.** A4 conflicts arrive D3; until then read `conflicts: []`.
When it lands you render what it returns — no interface change on your side.

---

## 7. Definition of done, per agent

Taken from the specs in `skills/`, not invented — so "done" is not a judgement call.

**A1 Query Analyst**
- Never rewrites a proper noun absent from the entity vocabulary.
- On low confidence, passes through unchanged with `warnings:["normalization_skipped"]`.
- Classifies intent: `direct / visual / comparison / multi_hop / contradiction / exploratory`.

**A3 Sufficiency Critic** — *the centre of sub-track 1C*
- **`next_query` on a multi-hop question contains a term that first appeared in the
  previous step's results.** This is the test that proves the loop reasons rather than
  rephrases, and it is what `gain_per_step` measures.
- Stops after 2 consecutive steps with no new evidence.
- Budget exhaustion yields `partial: true` with non-empty `missing[]` — *a partial honest
  answer, never a fabricated complete one*.
- `missing[]` entries are concrete: "the fourth and fifth signatory houses are not named",
  not "more information needed".

**A5 Answer Composer** — *sub-track 1A*
- Every material claim has `claim_id`, `citation_ids`, and a `support` label of
  `corroborated | single_source | disputed | inferred`.
- **Groundedness is computed from this**: `count(support != "inferred") / count(claims)`.
  A composer that returns prose without claims scores 0 forever — it cannot be retrofitted.
- Candidate assets are **scored and dropped below threshold**, not dumped. `asset_precision`
  is measured; attaching every retrieved image tanks it.
- `[FIG:id]` sits at the claim the figure supports, not in a gallery at the end.
- Tables render as tables. A prose summary of a table is a worse answer than the table.

**A6 Verifier**
- Every `[FIG:id]` resolves to a returned visual; every `doc_id` is real.
- Failing claims are downgraded to `support:"inferred"`, not shipped. *Removing a bad
  claim always beats shipping it.*

---

## 8. The prompt-injection rule

The archive contains in-world orders, decrees and trial transcripts — **text shaped like
instructions**. This is differentiator #8 and gets demoed on video.

> **Retrieved text always enters the prompt inside a delimited evidence block, never in
> the instruction position.**

Log any span matching instruction-like language and emit the
`instruction_like_text_in_source` warning on the packet. Build this into the composer's
first version; retrofitting it means auditing every prompt you have written.

---

## 9. Rules of engagement

1. **Branch, PR, cross-review, merge without squashing.** `feat/a5-composer`,
   `feat/orchestrator`. The rubric assesses this directly, and P1 reviews your PRs.
2. **Conventional commits**, one logical change each. Never `git add .` on a day's work.
3. **`data/` is gitignored** — corpus, index, and 65 MB of model weights. Never force-add
   anything under it. The submission ships the full `.git`, so a blob there is permanent.
4. **Never fabricate history.** We started late; the compressed timeline is recorded
   honestly in `docs/decisions.md`.
5. **Keep your Codex transcripts.** Human–AI collaboration is 15% of the score and is
   assessed from them — corrections included, uncleaned. The moment you tell Codex *"no,
   that composer drops the citation ids, redo it"* is worth more than clean generated code.

---

## 10. If something looks wrong

- **`/v1/ready` says `not_ready`** — the index is not built. Re-run section 2.
- **503 from `/v1/search`** — Qdrant is not running: `docker compose up -d qdrant`.
- **First request takes 30 s** — the cross-encoder is downloading, once. Startup warms it
  afterwards.
- **A search returns nothing sensible** — check `mode`. `sparse` alone will not find
  paraphrases; `dense` alone will not separate Greyfell from Ironfell. `hybrid` is the
  default for a reason.
- **An entity will not resolve** — that is deliberate. Exact match only. Try the canonical
  name from `/v1/graph/neighbors` on a known entity first.

Anything in the knowledge layer that looks broken: raise it with P1 rather than working
around it. A workaround in your layer for a bug in ours is the one thing that will make
the two halves diverge.
