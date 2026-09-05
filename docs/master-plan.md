> **Precedence:** `CLAUDE.md` > `docs/corpus-findings.md` > **this document**.
> The findings were measured from the real corpus on 4 Sep; this plan was written
> before the corpus existed. Where they disagree, the findings win.

# MASTER BUILD PLAN — Ashen Era Archive Assistant
**SLIIT Codefest 2026 AI Competition · powered by IFS · all three sub-tracks**
**Final. Supersedes plan v1 and v2 — work from this document only.**

---

# 0. Constraints and operating rules

## 0.1 The clock

Submission closes **Wed 9 September 2026, 23:30**. Today is **Fri 4 September**. That is **5.5 working days**.

| Day | Date | Outcome |
|---|---|---|
| **D0** | Fri 4 Sep (evening, ~5h) | Contracts frozen, repo live, corpus profiled |
| **D1** | Sat 5 Sep | Full ingestion; API answering end-to-end on fixtures |
| **D2** | Sun 6 Sep | Real hybrid retrieval; **Mode A working with real figures**; first eval numbers |
| **D3** | Mon 7 Sep | **Mode B** multi-hop with hop chains; **Mode C** agent loop |
| **D4** | Tue 8 Sep | Conflicts, router, verifier, full ablation table, Postman green |
| **D5** | Wed 9 Sep | **Freeze 12:00.** Docs, report, video. **Submit 20:00** |

## 0.2 Non-negotiable rules

1. **Code freeze D5 12:00.** No features after D4 23:59. The rubric is 25% "does it work" and 50% documentation, judgment, collaboration and presentation combined. A working 80% system with an excellent report beats a broken 100% system with none.
2. **Submit at 20:00, not 23:00.** Upload failures at deadline are the most common way good teams lose.
3. **Every feature must create evidence** — a metric, a trace, a citation, a test result, a decision record, or a live demo moment. If it produces none of those, it does not get built.
4. **Never fabricate git history.** You started late. Judges check timestamps and can contact you. 60–80 real atomic commits across 5 days reads as intense work. Note the compressed timeline honestly in `docs/decisions.md`.
5. **Freeze the schemas on D0.** `Block`, `Claim`, and the answer packet cannot be changed after D1 without a rewrite.
6. **No framework.** No LangChain, no LlamaIndex. See §3.

## 0.3 Cut-line ladder

Cut in this exact order the moment you are behind. Do not improvise this at 2am.

1. Debug page (`/debug/page/{doc}/{n}`)
2. Evidence-graph visualisation in the UI (keep the JSON — render it statically in the report)
3. VLM figure descriptions → caption + OCR text only
4. Graph path-finding → 2-hop neighbour expansion only
5. Ablation configs 2, 3, 6 (the story survives on six rows)
6. Streaming/SSE → plain JSON responses

**Never cut:** conflict detection, `missing_information`, the eval harness, the Postman collection, the README reproducibility path. Those are half your score.

---

# 1. Strategy

## 1.1 Winning thesis

> **One evidence-first reasoning engine. Sub-track 1B is the technical spine, 1C is its search-and-sufficiency loop, 1A is its rich answer renderer.**

This is the framing sentence for the report, the video, and every judge conversation. It matters because the challenge document warns that a strong single sub-track beats a shallow attempt at several. A hierarchy is one product. A menu is three shallow features.

The system is a single pipeline: understand the archive → find connected facts → investigate what is missing → merge evidence and expose conflicts → present text with the actual figures beside it.

## 1.2 What every other team ships

LangChain → Chroma → OpenAI embeddings → one vector lookup → GPT answer → Streamlit. No OCR. No figures. No graph. No evaluation numbers. By submission #6 the judges will not be able to tell them apart.

## 1.3 The nine differentiators

Ranked by impact × rarity. These are what actually win.

| # | Differentiator | Why it scores |
|---|---|---|
| 1 | **Source authority tiers + explicit contradiction surfacing** | The challenge document itself says "a tavern ballad and an official codex entry do not always agree." Almost nobody will build for it. Tier every source, detect conflicting claims, render "Disputed" answers with both sides and the resolution reason. → *Problem insight (15%)* |
| 2 | **Ablation table with real numbers** | BM25 → dense → hybrid → +rerank → +graph → +agentic, measured. The single highest-leverage page in your submission. → *Technical execution (25%) + judgment (10%)* |
| 3 | **Claim-level citations** | Every material claim carries its own citation IDs and a support label. Makes groundedness a computed number, not an opinion. |
| 4 | **`coverage@k` as a custom metric** | Standard recall rewards finding *a* relevant document. 1B needs *all* of them. Inventing the right metric for your own problem is a senior-engineer signal. |
| 5 | **Visible reasoning trajectory** | Every agent step logged and rendered live: query issued, what it learned, what was still missing, next query. Makes 1C *demonstrable* rather than claimed. |
| 6 | **Entity-aware typo correction** | The corpus is invented proper nouns. Standard spell-correction turns "Veyra Sunder" into something real and kills retrieval. Correct only against the entity vocabulary, show the correction, allow rollback. Judges will misspell names. |
| 7 | **Correct refusal + `missing_information`** | Judges will ask something not in the corpus. Every other system hallucinates. Yours says what it can establish, what it cannot, and names the nearest related material. |
| 8 | **Prompt injection treated as architecture** | The archive contains in-world orders, decrees and transcripts — text that *looks* like instructions. Evidence always enters prompts inside a delimited block, never in the instruction position. Demo this live. |
| 9 | **Judge-set-from-README reproducibility** | `git clone && cp .env.example .env && docker compose up && make demo` → answering questions in under 10 minutes. The rubric asks this literally. |

## 1.4 Explicitly out of scope

Cut now so they cannot creep back: fine-tuning, GraphRAG community summarisation, Neo4j, Kubernetes, multi-user auth, persistent/pinned conversation memory, self-healing or self-improvement loops, a source-upload registry UI, model routing tiers beyond two models, and thousands of synthetic questions.

Each of those is a day of work for near-zero rubric points. Their value is already captured by the failure taxonomy, the regression gate, and the ablation table.

---

# 2. Architecture

## 2.1 System diagram

```
                       ┌───────────────────────────────────────┐
                       │   React UI (Vite + Tailwind)          │
                       │  chat · inline figures · citation     │
                       │  page-crops · trace panel · eval page │
                       └───────────────────┬───────────────────┘
                                           │ REST /v1 + SSE
                       ┌───────────────────▼───────────────────┐
                       │        FastAPI  (OpenAPI 3.1)         │
                       └───────────────────┬───────────────────┘
                                           │
        ┌──────────────────────────────────▼──────────────────────────────────┐
        │                    ORCHESTRATOR  (explicit state machine)           │
        │                                                                     │
        │   A1 Query Analyst → A2 Retrieval → A3 Sufficiency Critic           │
        │            ↑______________________________|  (loop, budgeted)       │
        │   → A4 Evidence Merger → A5 Answer Composer → A6 Verifier           │
        │                                                                     │
        │   Router picks entry behaviour: auto | rich(1A) | graph(1B) | agent │
        └───────────────────┬─────────────────────────────────────────────────┘
                            │  A2's toolbox is where 1A and 1B live
        ┌───────────────────▼─────────────────────────────────────────────────┐
        │  RETRIEVAL CORE                                                     │
        │  hybrid(dense + BM25) → RRF → rerank → filter → neighbour expand    │
        │  graph_neighbors · graph_paths · figure_search · read_section       │
        └───────────────────┬─────────────────────────────────────────────────┘
                            │
   ┌────────────┬───────────┼────────────┬─────────────┬────────────────────┐
   │            │           │            │             │                    │
┌──▼─────┐ ┌────▼────┐ ┌────▼───────┐ ┌──▼────────┐ ┌──▼──────────────┐
│ Qdrant │ │ BM25s   │ │ Entity     │ │ Asset     │ │ Trace + Cache   │
│ dense  │ │ sparse  │ │ Graph      │ │ Registry  │ │ + Usage log     │
│        │ │         │ │ SQLite +   │ │ figures/  │ │ SQLite          │
│        │ │         │ │ NetworkX   │ │ tables    │ │                 │
└────────┘ └─────────┘ └────────────┘ └───────────┘ └─────────────────┘
   ▲            ▲            ▲             ▲
   └────────────┴─────┬──────┴─────────────┘
                      │
   ┌──────────────────▼──────────────────────────────────────────────┐
   │  INGESTION PIPELINE  (resumable, checksum-incremental)          │
   │  discover → format adapter → scan-detect → OCR/VLM →            │
   │  block extraction (text/table/figure/caption + bbox) →          │
   │  tier assignment → structure-aware chunk → embed →              │
   │  entity + relation extract → index                              │
   │  failures → dead-letter list, never halt the run                │
   └──────────────────┬──────────────────────────────────────────────┘
                      │
        ┌─────────────▼──────────────┐
        │   Ashen Era Archive        │
        │   415 docs · ~1,277 pages  │
        │   PDF · DOCX · MD · TXT    │
        │   images · simulated scans │
        │   READ-ONLY                │
        └────────────────────────────┘
```

Produce three diagrams for `docs/diagrams/`: this architecture, the ingestion data flow with the `Block` schema, and **a real Mode C trajectory taken from an actual trace**. The third is worth more than the other two combined — a generic boxes diagram proves nothing; a real trajectory proves the loop works.

## 2.2 Data model — freeze on D0

```python
Document:  doc_id, path, title, source_type, authority_tier, format,
           page_count, checksum, version, ingest_status, ingested_at

Block:     block_id, doc_id, page, order,
           block_type: text | table | figure | caption | heading,
           text,                    # figures: VLM description + OCR text
           asset_path, bbox, section_path,   # ["Vol II","Ch 4","The Siege"]
           caption_ref, ocr_confidence, token_count, checksum

Chunk:     chunk_id, doc_id, block_ids[], text, page_span, section_path,
           authority_tier, source_type, embedding_id, asset_ids[]

Entity:    entity_id, canonical_name, type, aliases[], mention_count
Relation:  subject_id, predicate, object_id, evidence_chunk_id,
           authority_tier, confidence

Claim:     claim_id, text, citation_ids[], support, confidence
           # support: corroborated | single_source | disputed | inferred
```

Every graph edge carries `evidence_chunk_id`. No unsourced edges, ever.

## 2.3 Authority tiers

The backbone of differentiator #1. Assign at ingestion from source type and filename patterns.

| Tier | Class | Examples |
|---|---|---|
| 1 | Official reference | codex data books, figure plates, canonical tables |
| 2 | Encyclopaedic | wiki articles |
| 3 | Primary narrative | the four novel volumes |
| 4 | Primary record | letters, ledgers, trial transcripts |
| 5 | Unreliable / folkloric | ballads, tavern tales, in-world rumour and hearsay |

Tier 4 is *primary evidence but partial*; tier 5 is *attested but unreliable*. Say exactly this in the report — it shows you reasoned about epistemics, not just file extensions.

## 2.4 The answer packet — the whole system in one object

```json
{
  "trace_id": "tr_01J...",
  "mode": "agent",
  "answer_markdown": "The Concord dissolved after the Third Ashguard withdrew [FIG:fig_0421] ...",

  "claims": [
    { "claim_id": "cl_1",
      "text": "The Ashfall Concord dissolved in 412 AE.",
      "citation_ids": ["c1", "c3"],
      "support": "corroborated",
      "confidence": 0.88 }
  ],

  "citations": [
    { "id": "c1", "chunk_id": "...", "doc_id": "codex_02",
      "title": "Codex of Cinders", "page": 88,
      "bbox": [72, 410, 520, 468],
      "section_path": ["Vol II", "Appendix C"],
      "source_type": "codex", "authority_tier": 1,
      "excerpt": "...", "excerpt_sha256": "9f3a...",
      "score": 0.93, "relation": "supports" }
  ],

  "visuals": [
    { "id": "fig_0421", "type": "figure",
      "url": "/v1/assets/fig_0421",
      "caption": "Plate IV — Concord seal variants",
      "doc_id": "codex_02", "page": 88, "bbox": [64, 120, 540, 390],
      "relevance": 0.91,
      "why": "Shows the three seal variants named in the answer." }
  ],

  "evidence_graph": {
    "nodes": [{ "id": "n1", "type": "entity|claim|document|visual|sub_question", "label": "..." }],
    "edges": [{ "from": "n1", "to": "n4", "type": "supports|contradicts|retrieved_from|merged_into" }],
    "paths": [["Veyra Sunder","served_under","Marshal Oren","commanded","Third Ashguard"]]
  },

  "conflicts": [
    { "attribute": "Concord dissolution year",
      "claim_a": "412 AE", "sources_a": ["codex_02 p88","ledger_044"], "tier_a": 1,
      "claim_b": "419 AE", "sources_b": ["ballad_017"],                "tier_b": 5,
      "resolution": "tier_1_corroborated",
      "rationale": "Codex entry corroborated by an independent ledger; the ballad is folkloric." }
  ],

  "missing_information": ["The archive does not name the fourth signatory house."],

  "warnings": [
    { "type": "low_ocr_confidence", "doc_id": "scan_112", "page": 3, "value": 0.61 },
    { "type": "instruction_like_text_in_source", "chunk_id": "...", "action": "treated_as_data" }
  ],

  "confidence": 0.81,
  "iterations": 3,

  "reasoning_trace": [
    { "step": 1, "agent": "retrieval", "action": "hybrid_search",
      "query": "Ashfall Concord dissolution", "found": 8, "new_gold_docs": 3,
      "learned": "Five signatory houses; two named here",
      "missing": "identities of the remaining three", "latency_ms": 412 }
  ],

  "usage": [
    { "step": 1, "model": "deepseek-chat",
      "routing_reason": "synthesis_requires_reasoning",
      "tokens_in": 4210, "tokens_out": 302, "latency_ms": 1180,
      "cost_usd": 0.0009, "cache": "miss", "fallback_used": false }
  ]
}
```

`[FIG:asset_id]` markers inline in `answer_markdown` are how the UI knows where to render a figure. That is sub-track 1A's entire core mechanic, expressed as one line of contract.

**`claims[]` is the piece that cannot be retrofitted.** Groundedness becomes `count(claims where support != "inferred") / count(claims)` — computed, not judged. Build it in on D0.

## 2.5 API surface

```
GET   /v1/health                        liveness
GET   /v1/ready                         index counts, model reachability, warm state
POST  /v1/ingestions                    {paths[], force} → job_id
GET   /v1/ingestions/{id}               progress, per-stage counts, warnings, dead-letter
POST  /v1/search                        retrieval primitive
                                        {mode: dense|sparse|hybrid, k, rerank,
                                         filters:{source_type, authority_tier, doc_id}}
POST  /v1/graph/neighbors               {entity, hops, rel_types[]} → subgraph
POST  /v1/graph/paths                   {from, to, max_hops} → paths + evidence
POST  /v1/chat                          {question, mode, budget, conversation_id}
                                        → answer packet
GET   /v1/chat/stream                   SSE: tokens + step events
GET   /v1/assets/{id}                   PNG (figure) | JSON+HTML (table) | page crop
GET   /v1/documents/{id}                metadata
GET   /v1/documents/{id}/pages/{n}      blocks, assets, bboxes — citation preview
GET   /v1/traces/{id}                   full trajectory
POST  /v1/evaluations                   {suite, modes[], ablation} → run_id
GET   /v1/evaluations/{id}              metrics table, failures by taxonomy
GET   /v1/metrics                       latency, cost, cache hit rate, token usage
GET   /debug/page/{doc}/{n}             blocks + bboxes + OCR confidence (cut-line #1)
```

---

# 3. Stack decisions

Copy this table into `docs/decisions.md` and expand each row into an ADR.

| Layer | Choice | Why this over the alternative |
|---|---|---|
| Runtime | Python 3.11 | Parsing + ML ecosystem |
| Packaging | `uv` + committed `uv.lock` | Reproducibility marks; ~10× faster than pip in CI |
| API | FastAPI + Pydantic v2 | Auto OpenAPI 3.1 → imports straight into Postman; validation free |
| PDF (digital) | PyMuPDF (`fitz`) | Text blocks with coordinates, image extraction with bbox, fast. Beats `unstructured` on speed and dependency weight |
| PDF tables | `pdfplumber` | Better ruling-line detection for the codex tables |
| Scan detection | text-layer density heuristic (<50 chars/page) | Cheap, deterministic, routes to OCR only when needed |
| OCR | Tesseract, VLM fallback below confidence threshold | Free, offline, no rate limits; VLM only where Tesseract is weak — controls cost |
| DOCX | `python-docx` | Tables → markdown; embedded images via relationship IDs |
| Figure description | free vision model on OpenRouter (Qwen2.5-VL / Llama Vision) | Makes figures *searchable* by embedding their description. This is what makes 1A actually work |
| Embeddings | Voyage `voyage-4-large` (docs) + `voyage-4-lite` (queries) | 200M free tokens. Shared vector space → asymmetric embedding with no re-index. Corpus ≈1.1M tokens with overlap, so you can re-index 100+ times inside the free tier |
| Sparse | `bm25s` | 10–100× faster than `rank_bm25`. Rare invented proper nouns are exactly where BM25 beats dense |
| Fusion | Reciprocal Rank Fusion, k=60 | No score normalisation needed; 15 lines you can defend under questioning |
| Reranker | Voyage `rerank-2.5` | Included in the free allowance. Biggest quality jump per line of code — prove it in the ablation |
| Vector store | Qdrant (docker) | Named vectors, payload filtering on `authority_tier` / `source_type`, one line in compose |
| Graph | SQLite tables + NetworkX at runtime | No extra service; the whole graph fits in memory at this scale. Neo4j is infra tax with zero benefit |
| LLM | OpenRouter → DeepSeek (synthesis), free model (extraction/classification) | One key, OpenAI-compatible, cheap. Two tiers only — do not build a routing engine |
| Structured output | JSON schema + Pydantic validation + repair retry | Entity extraction must not break the pipeline on one malformed response |
| Orchestration | **your own code** | Every member must "explain, justify, and modify any part on demand" in the final round. You can defend 400 lines of your own retrieval code. You cannot defend framework internals |
| Cache | SQLite keyed on `sha256(model + prompt + params)` | Cuts eval re-runs to near-zero cost and protects the demo from 429s |
| UI | Vite + React + Tailwind | Fast build, full control over figure and trace rendering |
| Tests | pytest + Postman/Newman | Unit + contract + regression gates |
| CI | GitHub Actions | Lint, tests, Newman, eval smoke, secret scan |

---

# 4. The six runtime agents

These are **bounded roles in an explicit state machine**, not autonomous agents. Each is a prompt file + JSON schema + validator + stop rule. When a judge asks "is it agentic?", say exactly that — the precise answer scores better than "we used an agent framework."

```
A1 Query Analyst
      ↓
A2 Retrieval  ←──────────┐
      ↓                  │  loop, hard-budgeted
A3 Sufficiency Critic ───┘
      ↓ (sufficient | budget exhausted)
A4 Evidence Merger
      ↓
A5 Answer Composer
      ↓
A6 Verifier
      ↓
   respond
```

Write each as `skills/<name>.md` with this header. The same file is the spec, the prompt, and the documentation — and it goes into `ai_usage/skills/` for submission.

```markdown
# Agent: <name>
Trigger: · Objective: · Tools: · Input schema: · Output schema:
Ordered steps: · Stop rules: · Failure modes & fallback: · Tests:
```

| ID | Agent | Job | In → Out | Tools | Stop rule | Failure fallback |
|---|---|---|---|---|---|---|
| **A1** | Query Analyst | Normalise without destroying invented proper nouns — fuzzy-match tokens against the **entity vocabulary only**, never a general dictionary. Classify intent (`direct / visual / comparison / multi_hop / contradiction / exploratory`). Decompose into sub-questions. Link seed entities. | `question` → `{normalized, corrections[], intent, sub_questions[], seed_entities[]}` | entity vocabulary, alias table | single pass | On low confidence pass the query through unchanged with `warnings:["normalization_skipped"]`. Never silently rewrite a name |
| **A2** | Retrieval Agent | Execute one retrieval action. Tool executor, not decision-maker — A3 decides what comes next. | `{action, query, filters, k}` → `{chunks[], assets[], entities[], subgraph}` | `hybrid_search`, `graph_neighbors`, `graph_paths`, `figure_search`, `read_section`, `list_mentions` | one action per call | Retry with backoff; on total failure return empty with a warning rather than raising — the loop must survive a dead tool |
| **A3** | Sufficiency Critic | The heart of 1C, described almost literally in the challenge document. Given everything gathered: is it enough? If not, what specifically is missing, and what is the best next action *given what was just learned*? | `{question, sub_questions, evidence_so_far, steps_taken}` → `{sufficient, covered[], missing[], next_action, next_query, reason}` | none — pure reasoning over state | `sufficient=true` · step budget 6 · token/wall-clock budget · **no new evidence for 2 consecutive steps** | On exhaustion hand to A5 with `partial=true` and unresolved `missing[]`. A partial honest answer, never a fabricated complete one |
| **A4** | Evidence Merger | Deduplicate chunks, cluster assertions by (entity, attribute), detect contradictions, resolve by authority tier with corroboration count as tiebreak. | `{chunks[], subgraph}` → `{evidence_bundle, conflicts[], reliability_notes[]}` | tier table, entity index | deterministic single pass | If tiers are equal and sources conflict, do **not** pick — emit `resolution:"unresolved"` and surface both. That behaviour is a feature; say so in the report |
| **A5** | Answer Composer | Write the answer as discrete claims, each bound to citation IDs. Place `[FIG:id]` markers where the figure supports the claim, not at the end. Score every candidate visual and drop anything below threshold. | `{question, evidence_bundle, conflicts, missing}` → `answer_markdown, claims[], visuals[]` | asset registry, relevance scorer | composition complete | If evidence supports nothing, return empty claims plus `missing_information[]`. Never compose from model knowledge — the world is invented, so anything the model "knows" is hallucinated by definition |
| **A6** | Verifier | Post-hoc gate before the response leaves. Every claim entailed by its cited chunks? Every `[FIG:id]` resolves to a returned visual? Every `doc_id` real? Strip or downgrade what fails. | packet → verified packet + `warnings[]` | entailment check, registry lookups | single pass | Downgrade a failing claim to `support:"inferred"` and lower confidence. Removing a bad claim always beats shipping it |

**Cross-cutting rule for A2 and A5.** Retrieved text always enters the prompt inside a delimited evidence block, never in the instruction position. The archive contains in-world orders, decrees and transcripts — text that *looks* like instructions. Log any span matching instruction-like language and set the `instruction_like_text_in_source` warning. Demo this on video using a corpus document that contains an in-world command. Every other team will be silently vulnerable.

---

# 5. Team and schedule

## 5.1 The split

Two builders. The seam is **`POST /v1/search`**, frozen D0 and never renegotiated. P1 owns everything that produces evidence; P2 owns everything that consumes it. P2 codes against fixtures until D2 morning, so neither is ever blocked.

| | **P1 — Knowledge layer (Eyaas)** | **P2 — Reasoning & delivery layer** |
|---|---|---|
| Owns | corpus → searchable structure | question → answer packet |
| Modules | `ingestion/` `indexing/` `retrieval/` `graph/` | `api/` `agents/` `synthesis/` `core/` `ui/` `eval/runner` |
| Builds | parsers, scan detection, OCR, figure/table extraction with bbox, caption linking, chunker, tier assignment, embeddings, Qdrant, BM25, RRF, rerank, neighbour expansion, entity + relation extraction, canonicalisation, graph store, traversal, evidence bundling, **conflict detection (A4 backend)** | FastAPI + schemas, orchestrator state machine, agents A1–A6, answer composer, figure relevance scorer, marker placement, trace store, budgets, redundancy guard, router, UI, Postman/Newman, CI, eval runner |
| Owns metrics | recall@k, coverage@k, nDCG, MRR, extraction failure rate, OCR confidence distribution, **the ablation table** | groundedness, citation precision/recall, refusal accuracy, asset precision/recall, success@budget, redundancy rate, gain_per_step, p95 latency, cost/query |
| Reviews | every P2 PR | every P1 PR |

**Members 3 and 4.** The rules require exactly 4 members and the final round disqualifies anyone who cannot explain and modify any part. Two silent members is a disqualification risk, not a staffing detail.

- **M3 — Gold set owner.** Hand-authors all 100 evaluation questions with gold answers, gold supporting documents, gold assets, and expected hop chains, read directly from the corpus. 10+ hours of real work, foundation of every number in the report, and it forces the deep corpus knowledge that makes them defensible under questioning.
- **M4 — Evidence & narrative owner.** Runs the decision diary (human hypothesis → AI suggestion → team correction → experiment → metric → decision → commit), writes the report, builds diagrams, cuts the video, exports and reviews AI chat logs, and runs the daily 20-minute interrogation drill on the two builders.

Both attend every 17:00 benchmark. By D4 both must walk through the full query path aloud, unaided. Test it — have them explain it to each other while you listen.

## 5.2 Daily rhythm

**09:00** each person names one measurable outcome · **13:00** integrate on `main` · **17:00** run the eval suite, record the delta in `decisions.md` · **21:00** freeze, push, export AI logs, 20-minute interrogation drill.

## 5.3 Day by day

### D0 — Friday evening (~5h)

| P1 | P2 |
|---|---|
| Corpus profiler → `docs/corpus-profile.md`: counts by extension, page counts, **text-layer density per PDF page**, image count, table candidates, char histogram | Repo skeleton, `uv init`, pre-commit (ruff/black/mypy), `docker-compose.yml`, `.env.example`, `Makefile`, FastAPI skeleton, `schemas.py`, `core/retry.py`, `core/cache.py`, `core/trace.py` |
| Ingestion contracts written into `docs/architecture.md` | Postman workspace + environments; `/v1/health` green |

Both: freeze `Block` / `Claim` / answer packet. All four members create OpenRouter keys (4 × 50 free req/day = 200/day for dev); one adds a card to Voyage. `.env` in `.gitignore` from commit #1. Write `CLAUDE.md`, ADR-000 (1B spine / 1C loop / 1A renderer) and ADR-001 (no framework). M3 starts the gold set from `sample_questions.json`.

**Gate:** schemas frozen, `/v1/health` green, 10 commits pushed.

**Build retry-with-backoff and the response cache on day zero.** The challenge document warns explicitly that systems without it "fail unpredictably, including during your demo recording."

### D1 — Saturday

| P1 | P2 |
|---|---|
| Format adapters: PDF (digital), DOCX, MD, TXT — preserve `section_path` from headings | `/v1/search` returning **fixtures** |
| Scan detection → Tesseract → confidence check → VLM fallback; log confidence per page | Orchestrator state machine shell |
| Figure + table extraction with bbox; caption linking (vertical proximity + `Fig./Plate/Table N` regex); assets → `data/assets/` | **A1 Query Analyst** (entity-aware normalisation) |
| Structure-aware chunker: ~600 tokens, 15% overlap, **never split a table**, figures are standalone chunks carrying caption + neighbouring paragraph | Trace persistence + `/v1/traces/{id}` |
| Tier assignment rules; log the distribution | Postman folders 00–02 |
| Resumable ingestion: per-file status, dead-letter list, never halt the run | |

**Gate:** 415 documents → blocks with a visible dead-letter list; the API returns a complete answer packet end-to-end on fixtures.

### D2 — Sunday

| P1 | P2 |
|---|---|
| **AM:** embed → Qdrant; build BM25; hybrid + RRF + rerank as three separately toggleable functions → **real `/v1/search`** | **AM: A2 Retrieval + A5 Composer → Mode A working with real figures.** Relevance scorer, marker placement, `/v1/assets/{id}`, table-as-table rendering, UI v1 with inline figures and citation chips → page-crop modal |
| **PM:** launch entity + relation extraction batch (runs overnight): fixed schema `Character, Faction, Artifact, Event, Location, Component, Title`, structured output, batched, cached, validated | **PM:** eval runner v1 → first recall@10, coverage@10, groundedness numbers |

**Gate:** a figure question returns the actual figure inline, cited, from real retrieval.
**17:00 decision:** pick the single strongest measurable differentiator from real results and optimise everything remaining around proving it.

### D3 — Monday

| P1 | P2 |
|---|---|
| Entity canonicalisation: fuzzy + embedding similarity, LLM adjudication only for the ambiguous band; log every merge (good ADR material) | **A3 Sufficiency Critic** |
| Graph build in SQLite + NetworkX load; every edge carries `evidence_chunk_id` and tier | Agent loop with hard budgets (6 steps, token cap, wall-clock cap) |
| k-hop expansion (cap 3) + shortest/all-paths with subgraph size cap | **Redundancy guard**: embed issued queries, block near-duplicates, report `redundancy_rate` |
| Evidence bundling in **hop order** → **Mode B**; synthesis prompt forces the explicit chain "A → B because…; B → C because…" | Trace panel in UI, updating live → **Mode C** |
| `coverage@k` wired into eval | Evidence-graph viz (cut-line #2) |

**Gate:** a 3-hop question answers with a visible hop chain; the agent runs a second search that demonstrably adds a gold document.

### D4 — Tuesday

| P1 | P2 |
|---|---|
| **A4 conflict detection**: cluster claims by (entity, attribute), flag contradictions, resolve by tier with corroboration tiebreak, emit `conflicts[]` | Router (`mode=auto`): figure-intent → A; ≥2 linked entities → B; decomposable → C. Manual override always available for the demo |
| Run **all nine ablation configs** | `missing_information` handling; **A6 Verifier** |
| Label every eval failure by taxonomy (extraction / retrieval / synthesis / refusal) | Full Postman collection + Newman in CI; UI polish; debug page |
| | Robustness pass: concurrency, empty query, 5k-char query, injection string, missing asset, Qdrant down |

**Both, evening:** each writes 20 unscripted questions the other has never seen; run them; record the honest pass rate.

**Gate:** ablation table complete with numbers; Newman green; unscripted pass rate recorded.

### D5 — Wednesday · freeze 12:00

| Time | Owner | Task |
|---|---|---|
| 09:00–11:00 | P1 | `README.md` — setup from zero, verified by someone who has never run it |
| 09:00–13:00 | all | `architecture.md`, `decisions.md` (8–12 ADRs), `limitations.md`, `evaluation.md` |
| 11:00–13:00 | M4 | Three diagrams, including the real trajectory |
| 12:00–16:00 | P1 + M4 | **`submission_report.pdf`** (5 pages max) |
| 13:00–14:00 | P2 | AI chat log export → `ai_usage/` + `ai-usage-disclosure.md` |
| 14:00–18:00 | M4 + M3 | Video record and edit |
| 18:00–18:30 | M4 | YouTube unlisted upload; link at top of report |
| 18:00–19:00 | P2 | Clean-clone verification: fresh machine, README only, must answer a question |
| 19:00–19:30 | P1 | ZIP with full `.git/`; `gitleaks detect` over the whole history |
| **20:00** | P1 | **Submit** |

---

# 6. Evaluation

Most submissions will have zero numbers. Yours will have a page of them.

## 6.1 Golden set — 100 questions, hand-labelled by M3

| Suite | n | Purpose | Gold labels |
|---|---|---|---|
| `sample` | 20 | The provided dev set | answer + supporting docs |
| `sample_variants` | 40 | 2 paraphrase/typo variants per official question | same gold as parent |
| `rich_1a` | 15 | Require a figure or table to answer correctly | answer + required `asset_id`s |
| `multihop_1b` | 20 | Need ≥3 documents; no single doc suffices | answer + full gold doc set + expected hop chain |
| `iterative_1c` | 15 | Cannot be resolved in one lookup | answer + minimum viable step count |
| `unanswerable` | 15 | Plausible but absent from the corpus | expected refusal + nearest related doc |
| `contradiction` | 10 | Sources disagree | expected conflict pair + expected resolution |
| `adversarial` | 5 | In-corpus injection, 5k-char query, gibberish, empty | expected safe behaviour |

Write gold labels **by hand, from the corpus**. LLM-generated gold is circular — you would be grading your retriever with your own generator, and judges may notice.

## 6.2 Metrics

**Retrieval** — `recall@k`, `precision@k`, `nDCG@10`, `MRR`, `first_relevant_rank`, and **`coverage@k`** (fraction of questions where *every* gold document appears in top-k — the metric that proves 1B).

**Answer** — `groundedness` (share of claims with `support != "inferred"`), `citation_precision` / `citation_recall`, `correctness` (LLM judge 0–3 against gold, plus human spot-check), `refusal_accuracy` and false-refusal rate, `conflict_f1`.

**Multimodal (1A)** — `asset_precision` / `asset_recall`, `asset_placement` (human-rated on 20 samples: is the figure referenced at the right point?).

**Agentic (1C)** — `success@budget`, `avg_steps`, `redundancy_rate`, and **`gain_per_step`** (new gold documents found per step — proves the loop learns rather than churns).

**System** — `p50/p95 latency`, `cost_usd/query`, `tokens/query`, `cache_hit_rate`, `429 rate`.

## 6.3 Failure taxonomy

Label every eval miss. Report the distribution — it turns a list of failures into a diagnosis.

| Label | Meaning | Fix lives in |
|---|---|---|
| `extraction` | the fact never made it out of the document | ingestion / OCR |
| `retrieval` | the gold chunk was not in top-k | index / fusion / rerank |
| `synthesis` | gold chunk *was* in context, answer still wrong | prompt / composer |
| `refusal` | refused an answerable question, or answered an unanswerable one | sufficiency critic / verifier |

Most teams conflate `retrieval` and `synthesis` and then optimise the wrong thing. Reporting the split is a strong judgment signal.

## 6.4 The ablation table — the most important page you will produce

| # | Config | Recall@10 | coverage@10 | nDCG@10 | Grounded | Correct | Retr. fail | Synth. fail | p95 ms | $/q |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | BM25 only | | | | | | | | | |
| 2 | Dense only (voyage-4-lite) | | | | | | | | | |
| 3 | Dense only (voyage-4-large) | | | | | | | | | |
| 4 | Hybrid RRF | | | | | | | | | |
| 5 | Hybrid + rerank-2.5 | | | | | | | | | |
| 6 | + neighbour/section expansion | | | | | | | | | |
| 7 | + graph expansion (Mode B) | | | | | | | | | |
| 8 | + agentic loop (Mode C) | | | | | | | | | |
| 9 | Full + conflict layer | | | | | | | | | |

Then write the sentence judges want to read:

> *"Rerank added +N points of recall@10 for +M ms. Graph expansion added +P points of coverage@10 on multi-hop questions specifically while adding nothing on single-hop — which is why the router only invokes it when entity linking finds ≥2 seeds."*

That is technical judgment, demonstrated rather than claimed.

## 6.5 Judge validation

Human-rate 20 questions and compare against the LLM judge. Report the agreement percentage. Almost no team validates their own evaluator, and doing so pre-empts the obvious challenge to every number in your report.

## 6.6 Failures to record deliberately

`docs/limitations.md` needs real failed experiments with numbers. Log them as they happen — you will not remember on D5.

- Chunk size sweep (300 / 600 / 1000) — what won and by how much
- Naive top-k without rerank — quantify the miss rate on multi-hop specifically
- Tesseract on the hardest simulated scans — where it broke and what the VLM fallback cost
- Entity schema v1 → v2 — what over-extracted, what got dropped
- Agent without the redundancy guard — the loop-churn rate you measured and fixed
- Any approach you abandoned, with the number that killed it

## 6.7 Regression gate

A pytest running a 10-question smoke eval in CI, failing the build if `recall@10` or `groundedness` drops more than 3 points from `eval/baseline.json`. Mention it in the README.

---

# 7. Postman and CI

## 7.1 Setup

FastAPI serves OpenAPI at `/openapi.json` → **Import → Link** in Postman; regenerate whenever the contract changes. Environments `local` and `docker` with `{{base_url}}`, `{{trace_id}}`, `{{job_id}}`, `{{known_doc_ids}}`. Export to `tests/postman/` and commit.

## 7.2 Collection

```
Ashen Era Archive Assistant
├── 00 Health          /v1/health, /v1/ready
├── 01 Ingestion       POST /v1/ingestions, GET polling loop
├── 02 Retrieval       /v1/search × {dense, sparse, hybrid, +rerank, +filters}
├── 03 Graph           /v1/graph/neighbors, /v1/graph/paths
├── 04 Chat — 1A       figure question, table question, image-only question
├── 05 Chat — 1B       3-hop, 4-hop, "what else is affected if X fails"
├── 06 Chat — 1C       decomposable question, budget-exhaustion case
├── 07 Chat — Router   mode=auto across all types
├── 08 Edge cases      unanswerable, empty, 5k chars, injection, bad doc_id, missing asset, typo'd entity name
├── 09 Assets & Docs   /v1/assets/{id}, /v1/documents/{id}/pages/{n}
├── 10 Traces          /v1/traces/{{trace_id}}
├── 11 Evaluations     POST /v1/evaluations, GET results
└── 12 Unscripted      40 questions neither builder wrote code against
```

Folder 12 is deliberate. The rubric asks *"does it actually work on inputs the team didn't script?"* — answer it with a number.

## 7.3 Assertions

```javascript
const r = pm.response.json();

pm.test("200 OK",              () => pm.response.to.have.status(200));
pm.test("latency budget",      () => pm.expect(pm.response.responseTime).to.be.below(8000));
pm.test("schema valid",        () => pm.response.to.have.jsonSchema(answerPacketSchema));
pm.test("has claims",          () => pm.expect(r.claims.length).to.be.above(0));
pm.test("every claim cited",   () => r.claims.forEach(c =>
                                     pm.expect(c.citation_ids.length).to.be.above(0)));
pm.test("cites real docs",     () => r.citations.forEach(c =>
                                     pm.expect(pm.collectionVariables.get("known_doc_ids"))
                                       .to.include(c.doc_id)));                 // hallucination check
pm.test("figure markers resolve", () => {
  const ids = [...r.answer_markdown.matchAll(/\[FIG:([^\]]+)\]/g)].map(m => m[1]);
  ids.forEach(id => pm.expect(r.visuals.map(v => v.id)).to.include(id));
});
pm.test("cost bounded",        () => pm.expect(
                                     r.usage.reduce((s,u) => s + u.cost_usd, 0)).to.be.below(0.02));

pm.collectionVariables.set("trace_id", r.trace_id);
```

Per-folder extras — **1A:** `visuals.length > 0` and every visual has `relevance > threshold`. **1B:** `evidence_graph.paths.length > 0` and citations span ≥3 distinct `doc_id`s. **1C:** `reasoning_trace.length >= 2` and `iterations <= budget`. **Unanswerable:** `missing_information.length > 0` and no `support:"corroborated"` claims. **Typo'd entity:** `corrections[]` non-empty and the answer still correct.

## 7.4 CI

```yaml
lint       → ruff · black --check · mypy
unit       → pytest -q --cov  (≥70% on src/core, src/retrieval, src/agents)
services   → docker compose up -d qdrant api ; wait for /v1/ready
contract   → newman run tests/postman/AshenEra.postman_collection.json \
               -e tests/postman/ci.environment.json \
               -r cli,htmlextra --reporter-htmlextra-export docs/reports/newman.html
eval-smoke → make eval SUITE=smoke && python eval/check_regression.py
secrets    → gitleaks detect --no-git=false
```

Commit the Newman HTML report into `docs/reports/`. A judge opening a green contract-test report is worth more than a paragraph claiming robustness.

---

# 8. Repository, git, AI usage evidence

## 8.1 Layout

```
ashen-era-assistant/
├── .git/
├── .github/workflows/ci.yml
├── README.md  Makefile  docker-compose.yml
├── pyproject.toml  uv.lock  .env.example  .gitignore
├── CLAUDE.md
├── .claude/
│   ├── agents/          # 8 subagent definitions
│   ├── skills/          # A1–A6 specs, code-style, eval-rubric
│   └── commands/        # /adr  /eval  /ingest-test
├── skills/              # runtime agent specs (A1–A6) — spec = prompt = doc
├── docs/
│   ├── architecture.md  decisions.md  limitations.md
│   ├── evaluation.md  corpus-profile.md
│   ├── diagrams/        # mermaid + png
│   └── reports/         # newman.html, eval runs
├── src/
│   ├── ingestion/   adapters/  ocr.py  figures.py  chunker.py  tiers.py  resume.py
│   ├── indexing/    embed.py  qdrant_store.py  bm25_store.py
│   ├── retrieval/   hybrid.py  rrf.py  rerank.py  expand.py
│   ├── graph/       extract.py  canonicalize.py  store.py  traverse.py
│   ├── agents/      analyst.py  retriever.py  critic.py  merger.py
│   │                composer.py  verifier.py  orchestrator.py  router.py
│   ├── synthesis/   prompts/  conflicts.py  citations.py  claims.py
│   ├── core/        llm.py  cache.py  retry.py  trace.py  usage.py  config.py
│   └── api/         main.py  routes/  schemas.py
├── ui/
├── eval/            suites/  metrics/  runner.py  baseline.json  taxonomy.py
├── tests/           unit/  integration/  postman/
├── ai_usage/
│   ├── ai-usage-disclosure.md
│   ├── logs/            # exported .txt transcripts
│   ├── skills/          # copy of .claude/skills + skills/
│   ├── claude.md
│   └── context.md
├── configuration-example/
├── scripts/         export_ai_logs.py  profile_corpus.py
└── submission_report.pdf
```

## 8.2 Git rules

Conventional commits (`feat(retrieval): add RRF fusion with configurable k`). One logical change per commit — never `git add .` on a day's work. Feature branch → PR → **reviewed by the other builder** → merge without squashing. Tags: `v0.1-ingestion`, `v0.2-hybrid`, `v0.3-mode-a`, `v0.4-graph`, `v0.5-agent`, `v1.0-submission`. `.env` in `.gitignore` from commit #1; `gitleaks` before zipping — a key in an old commit stays leaked, and the challenge document calls this out explicitly.

## 8.3 Human–AI collaboration evidence — 15% of the score

The rubric rewards *"iterative refinement, questioning and correcting AI output"* and penalises one-shot generation. Engineer the evidence honestly:

- **Each member drives their own Claude Code sessions.** Four voices in the logs is far more credible than one.
- **Keep the corrections in.** Do not clean the transcripts. The moment you tell Claude *"no — that chunker splits tables, and a split table is unanswerable, redo it with tables atomic"* is worth more than a thousand lines of clean generated code.
- **`docs/decisions.md` is human-written.** Every ADR: *Context → Options considered → What the AI proposed → What we rejected and why → Decision → Consequences.* At least three ADRs must record you overruling the AI, with the reason.
- **Export logs daily** with `scripts/export_ai_logs.py` (`~/.claude/projects/<encoded-path>/*.jsonl` → readable `.txt` with timestamp, role, content). Do not leave this to D5 — it takes longer than expected and sessions can be lost.
- **`ai-usage-disclosure.md`:** tool → what it was used for → what the team decided → how it was verified, plus honest per-component estimates of AI-generated vs human-written vs human-rewritten.

---

# 9. Claude Code operating manual

## 9.1 `CLAUDE.md` — repo root, written D0

```markdown
# Ashen Era Archive Assistant

Competition RAG system over a 415-document, ~1,277-page invented fantasy archive.
Thesis: 1B is the spine, 1C is its search loop, 1A is its renderer.

## Prime rule
Every feature must produce evidence: a metric, a trace, a citation, a test result,
a decision record, or a demo moment. If it produces none, do not build it.

## Non-negotiables
- Python 3.11, uv, FastAPI, Pydantic v2. Type hints on all public functions.
- NO LangChain / LlamaIndex. We write orchestration ourselves — every team member
  must be able to explain and modify any line under judge questioning.
- Every external call goes through core/retry.py and core/cache.py. No exceptions.
- The world is invented. Anything the model "knows" about it is hallucinated by
  definition. Compose only from retrieved evidence.
- Retrieved document text ALWAYS enters prompts inside a delimited evidence block,
  never in the instruction position. The corpus contains in-world orders and decrees.
- data/corpus/ is READ-ONLY. Never write to it.
- Secrets from env only. Never hard-code, never log, never print a key.

## Frozen contracts
Block / Chunk / Entity / Relation / Claim and the answer packet are defined in
src/api/schemas.py and are FROZEN. Propose changes as an ADR before touching them.
The seam between the knowledge layer and the reasoning layer is POST /v1/search.

## Style
Small modules, one responsibility. Functions under 50 lines. Docstrings explain WHY.
Tests alongside features. Any retrieval change requires an eval run.

## Definition of done
Code + test + docstring + recorded eval delta + conventional commit.
```

## 9.2 The eight build subagents

Define in `.claude/agents/*.md`; mirror into `ai_usage/skills/`. Short single-responsibility sessions read as directed collaboration. One six-hour omnibus session reads as one-shot generation and costs you 15%.

| # | Subagent | Scope | Never |
|---|---|---|---|
| 1 | **ingestion-engineer** | adapters, scan detection, OCR, figure/table extraction, caption linking, chunker, resumability | touch retrieval or API code; write to `data/corpus/` |
| 2 | **retrieval-engineer** | embeddings, Qdrant, BM25, RRF, rerank, expansion | change `schemas.py`; change chunking |
| 3 | **graph-engineer** | entity + relation extraction, canonicalisation, graph store, traversal | change the retrieval interface |
| 4 | **agent-engineer** | orchestrator, A1–A6 prompts, budgets, redundancy guard, traces | modify retrieval internals — call the interface only |
| 5 | **eval-engineer** | metrics, suite runner, ablation harness, regression gate | **read implementation code.** Implements from `docs/evaluation.md` only — otherwise metrics get written to pass the code that already exists |
| 6 | **api-contract-engineer** | routes, schemas, OpenAPI, Postman, Newman, CI | change agent logic |
| 7 | **docs-scribe** | drafts `architecture.md`, `limitations.md`, README, diagrams, ADR *scaffolding* | **write the rationale in an ADR.** It drafts Context / Options / Consequences; the human writes "what we rejected and why" |
| 8 | **adversarial-reviewer** | reviews each merged diff asking *"what would a judge ask about this that we could not answer?"*; red-teams the API with injection strings, empty inputs, 5k-char queries, malformed asset IDs | fix anything — it reports, the owner fixes |

Run #8 at the end of every day. Its output goes straight into `docs/limitations.md` and M4's interrogation drill. Cheapest insurance you can buy against the final round.

## 9.3 Session discipline

- **Plan mode before any non-trivial component.** Argue with the plan before code exists. That argument *is* your collaboration evidence.
- Always ask **"What's the case against this design?"** and record the answer. That is `decisions.md` writing itself.
- One component per session. Commit at the end of each.
- Custom commands in `.claude/commands/`: `/adr` (scaffold a decision record), `/eval` (run a suite and diff against baseline), `/ingest-test` (subset re-ingest + smoke retrieval).

## 9.4 Prompt patterns that produce defensible code

- *"Implement X. Before coding, list three approaches and the trade-off on latency, cost and recall. Wait for my choice."*
- *"This chunker splits tables across chunks. A split table is unanswerable. Redo it with tables atomic, and add a test asserting no chunk contains a partial table."*
- *"Write the failing test first, from the metric definition in docs/evaluation.md. Do not read the retrieval implementation."*
- *"Review this diff for anything a judge could ask about that we could not justify. List those lines."*

---

# 10. Deliverables

## 10.1 Rubric map

| Criterion | Weight | Your evidence |
|---|---|---|
| Technical execution & robustness | 25% | Working three-mode system; unscripted pass rate; Newman contract suite; edge cases; retry/backoff/cache; resumable ingestion; clean-clone reproducibility |
| Problem understanding & insight | 15% | Authority tiers + conflict surfacing; `coverage@k`; corpus profile driving design; entity-aware typo handling; injection-as-architecture; `missing_information` |
| Human–AI collaboration | 15% | Four members' chat logs with visible correction cycles; ADRs recording overrules; commit history; your own `skills/` specs |
| Engineering best practices | 15% | Atomic conventional commits; cross PR review; `uv.lock`; docker compose; ≥70% core coverage; CI; a README a judge can follow |
| Technical judgment & decisions | 10% | The ablation table; failure taxonomy distribution; `limitations.md` with quantified failures; judge validation of the LLM judge |
| Impact & relevance | 10% | Enterprise framing (the archive as a proxy for real technical documentation); provenance and auditability; cost per query; deployment notes |
| Presentation & documentation | 10% | 10-minute video with 4-minute unedited live demo; three diagrams; five-page report; rendered Newman and eval reports |

## 10.2 Report — 5 pages, hard limit

1. **p1** — YouTube link at the top. Problem, the 1B-spine thesis, architecture diagram.
2. **p2** — Ingestion and indexing decisions, driven by the corpus profile numbers.
3. **p3** — The three modes and the authority/conflict layer. A real Mode C trajectory from an actual trace.
4. **p4** — **Evaluation.** The ablation table. Failure taxonomy distribution. Judge-validation agreement. What failed, with numbers.
5. **p5** — Limitations, AI usage disclosure, team roles and contributions.

## 10.3 Video — 10:00 maximum

| Time | Content |
|---|---|
| 0:00–0:45 | The problem in enterprise terms. Show a naive-baseline failure, live |
| 0:45–2:00 | Architecture walkthrough. The 1B-spine argument |
| **2:00–6:30** | **Live, unedited, one take.** 1A figure question → figure renders inline with a page-crop citation. 1B "what else is affected if X fails" → hop chain + evidence graph. 1C decomposable question → trace panel updating live. Contradiction question → Disputed answer with tiers. Unanswerable question → correct refusal with `missing_information`. Typo'd entity name → correction shown, answer still right. Injection document → treated as data, warning surfaced. One question typed on camera by a team member that was never prepared |
| 6:30–8:00 | Evaluation: ablation table on screen; explain the two most interesting rows |
| 8:00–9:15 | Human–AI collaboration: an ADR where you overruled the AI; the commit graph; a chat log correction |
| 9:15–10:00 | Limitations, honestly. Close |

Warm the cache before recording so latency is representative, but do not pre-record. Say out loud that the demo segment is unedited.

---

# 11. Risk register

| Risk | Likelihood | Control |
|---|---|---|
| Rate limits (429) during the demo | High | Backoff from D0; four accounts; response cache; pre-warm before recording |
| OCR quality on simulated scans | High | VLM fallback; measure and **report** the OCR failure rate rather than hiding it |
| Entity extraction noise corrupts the graph | Medium | Confidence threshold; require ≥2 mentions for a node; log dropped entities |
| Agent loops without converging | Medium | Hard step/token/wall-clock budgets; no-new-evidence stop; redundancy guard |
| Index rebuild too slow to iterate | Medium | Checksum-incremental ingest; `--subset 30` dev flag |
| Scope creep across three tracks | High | The cut-line ladder in §0.3. Enforce it literally |
| One builder blocked, work stalls | Medium | Contracts frozen D0 means both code against interfaces, not each other |
| Synthetic or generated gold labels invent truth | Medium | Gold set is hand-authored by M3 from the corpus only |
| Prompt injection from corpus text | Medium | Evidence always delimited, never in instruction position; suspicious spans logged and surfaced |
| M3/M4 cannot defend the system in the final round | Medium | Daily 20-minute interrogation drill; both must walk the query path unaided by D4 |
| Video render or upload runs long | Medium | Record 14:00, upload by 18:30, submit 20:00 |
| Key leaked in git history | Low / fatal | `.gitignore` from commit #1; `gitleaks` in CI and before zipping |

---

# 12. Do these today

1. **Freeze the answer packet (§2.4) in `docs/architecture.md`.** The `claims[]` structure cannot be retrofitted — everything downstream depends on it.
2. Push commit #1: repo skeleton, `docker-compose.yml`, `.env.example`, `.gitignore`, `Makefile`.
3. Run the corpus profiler → `docs/corpus-profile.md`. The scanned-vs-born-digital ratio decides how much of Saturday goes to OCR, and it is the one number this plan is still guessing at.
4. Write the six `skills/*.md` agent specs as headers only — trigger, schemas, stop rules. Specs first, prompts second.
5. Write `CLAUDE.md`, ADR-000 (1B spine / 1C loop / 1A renderer), ADR-001 (no framework).
6. All four members create OpenRouter keys; one adds a card to Voyage.
7. M3 starts the gold set from `sample_questions.json`; M4 opens the decision diary.
8. Build `core/retry.py` and `core/cache.py` **before** the first API call is written.
