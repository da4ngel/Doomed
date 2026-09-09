# AI Usage Disclosure

**Project:** Ashen Era Archive Assistant — evidence-first RAG over a 415-document invented fantasy archive
**Competition:** SLIIT Codefest 2026 AI Competition, powered by IFS
**Submission date:** 9 September 2026
**Contributors (from git history):** Eyaas Ajmal, Ihthisham Irshad

> **`[TEAM: …]` markers** flag every statement that must be confirmed, corrected, or
> completed by the team before submission. This file was scaffolded with AI assistance
> from the repository's own history and artifacts; the judgement calls, percentage
> estimates, and verification claims are the team's to make. A disclosure we have not
> actually endorsed is not collaboration evidence — the same principle `docs/decisions.md`
> applies to its ADR rationales.

---

## 1. Summary

This project was built with **Claude Code** (Anthropic) as the primary development
assistant, driven interactively by the team through many short, task-scoped sessions
rather than one-shot generation. The workflow is visible in the repository itself:
`CLAUDE.md` (project constitution), `.claude/agents/*.md` (8 role-scoped build subagents),
`.claude/commands/*.md` (3 project slash commands), `skills/a1..a6-*.md` (agent
specifications that double as prompts and documentation), and 125 conventional commits
across 5–9 September 2026 authored by two people.

Two distinct kinds of AI use are disclosed here and must not be conflated:

| | **Build-time AI** | **Run-time AI (part of the product)** |
|---|---|---|
| What | Assistant used to write, review, and document code | LLM/VLM calls the deployed system makes to answer a question |
| Tools | Claude Code (Claude models) | OpenRouter / OpenAI (synthesis, sufficiency, verification); a vision model for figure description |
| Disclosed in | §2–§5 below | §6 below + `docs/decisions.md` ADR-002, ADR-004, ADR-005 |

---

## 2. Build-time AI — tools

| Tool | Provider | Used for | Team decision / control |
|---|---|---|---|
| Claude Code (CLI) | Anthropic | Code authoring, refactoring, test writing, doc drafting, debugging, code review, this evaluation run | Each change lands as a reviewed conventional commit on a feature branch; `CLAUDE.md` constrains scope, style, and the frozen contracts |
| Claude Code subagents (`.claude/agents/`) | Anthropic | Role-scoped work: `ingestion-engineer`, `retrieval-engineer`, `graph-engineer`, `agent-engineer`, `api-contract-engineer`, `eval-engineer`, `docs-scribe`, `adversarial-reviewer` | Single-responsibility sessions; `docs-scribe` is explicitly barred from writing ADR rationales; `adversarial-reviewer` reports only, never fixes |
| Claude Code slash commands (`.claude/commands/`) | Anthropic | `/adr` (scaffold a decision record), `/eval` (run a suite, diff the baseline), `/ingest-test` (subset re-ingest + smoke retrieval) | Deterministic wrappers around the team's own scripts |
| `[TEAM: any other assistants used — Copilot, ChatGPT, Cursor, etc.]` | | | |

**Models:** `[TEAM: confirm which Claude models — the repo shows Claude Code sessions; the`
`most recent evaluation session ran on Claude Sonnet. State the mix if known.]`

---

## 3. Build-time AI — what it did, per component, and how it was verified

`[TEAM: review each row. The "AI did" and "verified by" columns are drawn from the repo;`
`the "human decided / rewrote" column and the split estimate need your input.]`

| Component | AI did | Human decided / rewrote | Verified by |
|---|---|---|---|
| **Ingestion** (`src/ingestion/`) — adapters, OCR, scan routing, chunker, tier assignment | Drafted the format adapters, chunker, OCR degradation path, `assign_tier` | `[TEAM: e.g. "we set tables-atomic after AI's first chunker split a table; ADR-008 chunk size; ADR-003 directory-first tiers"]` | `uv run pytest` (unit + integration), `docs/reports/chunk-sweep.md`, structure-extraction agreement 93.8% (`docs/limitations.md` §9) |
| **Indexing / retrieval** (`src/indexing/`, `src/retrieval/`) — embeddings, Qdrant, BM25, RRF fusion, graph/section expansion | Drafted the hybrid pipeline, RRF, expansion | `[TEAM: ADR-004 local-first embeddings; ADR-009 additive expansion; the decision to gate LLM edges out of retrieval after they hurt coverage]` | `eval/runner.py` ablation vs `eval/baseline.json` (gate tolerance 0.001); `docs/reports/ablation.md` |
| **Graph** (`src/graph/`) — wiki extraction, SQLite/NetworkX store, traversal | Drafted the deterministic wiki-infobox extractor, the store, k-hop/path queries | `[TEAM: ADR-005 deterministic graph before any LLM extraction; entity resolution = article-stripping only, no fuzzy matching]` | `tests/unit/test_gold_1b_1c.py`; 379 wiki edges reproduced deterministically |
| **Reasoning agents** (`src/agents/`) — A1–A6 state machine, orchestrator, budgets, router | Drafted all six agents and the orchestrator from the `skills/aN-*.md` specs | `[TEAM: the specs themselves — who wrote them; ADR-001 no orchestration framework; budget ceilings raised from measured data]` | `tests/reasoning/` acceptance harness; `docs/reports/acceptance-2026-09-07.md`; `docs/reports/sample-questions-eval-2026-09-09.md` |
| **Synthesis** (`src/synthesis/`) — claims, citations, conflict detection, rendering, extractive figure path | Drafted verbatim-span citation matching, pattern-based conflict detection, the answer renderer | `[TEAM: pattern-based (not LLM) conflict detection was a deliberate choice — ADR / limitations §7]` | `tests/unit/test_gold_suites.py`; conflict precision 7/7 hand-verified (`docs/limitations.md` §7) |
| **API** (`src/api/`) — FastAPI routes, frozen Pydantic schemas | Drafted routes and schemas | `[TEAM: the frozen contracts — `Block`/`Chunk`/`Entity`/`Relation`/`Claim`/answer packet — and the `POST /v1/search` seam were designed by the team and frozen day zero]` | 69 Postman/Newman contract assertions (`docs/reports/newman.html`); `uv run pytest` |
| **Eval harness** (`eval/`) — metrics, suite runner, ablation, regression gate, failure taxonomy | Drafted the metric implementations and the runner | `[TEAM: `docs/evaluation.md` was written before `eval/metrics.py` deliberately, so the metric could "embarrass the implementation" — who wrote it]` | Metrics unit-tested (`tests/unit/test_metrics.py`, `test_regression_gate.py`) |
| **Gold answer sets** (`eval/suites/*.json`) | **None.** LLM-generated gold is explicitly forbidden (`.claude/agents/eval-engineer.md`) | `[TEAM: every gold label hand-authored from the corpus — who read which images/documents, on what dates. `rich_1a.json` says "read by a human directly from the source image on 2026-09-05"]` | Cross-checked by `tests/unit/test_gold_suites.py` against the real corpus |
| **Decision records** (`docs/decisions.md`) | Scaffolded Context / Options / Consequences and drafted "rejected and why" blocks, all marked `DRAFT — review` | `[TEAM: the "what we rejected and why" judgement must be in your own words and endorsed — the file's own DRAFT NOTICE says so. At least 3 ADRs should record the team overruling the AI.]` | N/A — human-authored artifact |
| **Documentation** (`README.md`, `docs/*.md`) | Drafted architecture.md, limitations.md, evaluation.md, RUNBOOK.md, diagrams | `[TEAM: which docs were rewritten vs. accepted]` | Numbers in `docs/` are reproducible from commands in the repo (`README.md` §"Reproduce the numbers") |

### Component-level AI / human split — `[TEAM: fill in honest estimates]`

| Component | AI-generated (accepted ~as-is) | Human-rewritten after AI draft | Human-written from scratch |
|---|---|---|---|
| Ingestion | `[TEAM %]` | `[TEAM %]` | `[TEAM %]` |
| Indexing / retrieval | `[TEAM %]` | `[TEAM %]` | `[TEAM %]` |
| Graph | `[TEAM %]` | `[TEAM %]` | `[TEAM %]` |
| Reasoning agents | `[TEAM %]` | `[TEAM %]` | `[TEAM %]` |
| Synthesis | `[TEAM %]` | `[TEAM %]` | `[TEAM %]` |
| API / schemas | `[TEAM %]` | `[TEAM %]` | `[TEAM %]` |
| Eval harness | `[TEAM %]` | `[TEAM %]` | `[TEAM %]` |
| Gold sets | 0% | 0% | 100% |
| ADR rationales | `[TEAM: 0% — must be human]` | `[TEAM %]` | `[TEAM %]` |
| Docs | `[TEAM %]` | `[TEAM %]` | `[TEAM %]` |

---

## 4. How the collaboration was iterative (not one-shot)

Evidence that the team questioned and corrected AI output rather than accepting it:

- **125 conventional commits** over five days (5–9 Sep 2026), one logical change each, on
  feature branches with PR review between the two builders — not a single bulk drop.
  Type breakdown: 35 `feat`, 34 `fix`, 34 `docs`, 4 `test`, 6 `chore`/`build`, 2 `perf`,
  1 `style`. The high `fix` count reflects real correction cycles.
- **`docs/decisions.md`** — 10 ADRs (ADR-000…009), each with an "options considered" and a
  "what we rejected and why" block. `[TEAM: name the ADRs where you overruled the AI —`
  `candidates from the record: ADR-001 (no framework, against the easier path), ADR-004`
  `(local embeddings over a paid Voyage key), ADR-005 (deterministic graph before LLM`
  `extraction), ADR-008 (chunk size from the model's context window, not a round number),`
  `ADR-009 (expansion must spend the same k budget).]`
- **Documented AI failures the team caught.** `docs/decisions.md` ADR-002 records the
  vision spike failing three times (retired model ids, a broken discovery path, a prompt
  that produced prose instead of label/value pairs) before it worked.
  `docs/reports/acceptance-2026-09-07.md` records finding and fixing: budget reservation
  counting UTF-8 bytes as tokens (~4× over), A6's entailment call silently 400-ing on
  every request, BM25 over-fetching 5× because an empty filter object is truthy, and
  every LLM call earning a guaranteed 402 before falling through to the right provider.
- **`docs/limitations.md`** — the team documents what the system does *not* do, with
  measured numbers, including results where an AI-proposed approach lost (reranking hurts
  multi-hop; LLM-extracted graph edges hurt retrieval coverage).
- **Session transcripts.** `[TEAM: state whether Claude Code session logs were exported`
  `(`~/.claude/projects/<encoded-path>/*.jsonl`) and where they are in the submission.`
  ``docs/master-plan.md` §8.3 planned `scripts/export_ai_logs.py` for this — confirm`
  `whether it was run.]`

---

## 5. Verification practices — how AI output was checked before it was trusted

| Practice | What it catches | Artifact |
|---|---|---|
| `uv run pytest` — `[TEAM: current count; README says 329]` tests, no Docker or API keys required | Regressions in ingestion, chunking, graph, synthesis, API contracts | CI: `.github/workflows/` |
| Retrieval regression gate — `uv run python -m eval.runner --suite all --ablation --gate` | Any drop in `recall@k` / `coverage@k` / `nDCG@k` / `mrr` below `eval/baseline.json` (tolerance 0.001) | `docs/reports/ablation.md` |
| Answer-level acceptance — `tests/reasoning/acceptance.py` + human review (`human-review.csv`, 0–3 per answer) | Wrong or ungrounded answers; the harness's own verdict is `manual_review_required` and does not self-certify | `docs/reports/acceptance-2026-09-07.md`, `docs/reports/sample-questions-eval-2026-09-09.md` |
| 69 Postman/Newman contract assertions | API responses that violate the frozen schema | `docs/reports/newman.html` |
| Groundedness computed, not judged — `count(claims where support != "inferred") / count(claims)` | Claims without a verbatim citation | Built into the answer packet (`src/api/schemas.py`) |
| `gitleaks` before packaging | A secret committed in any historical commit | `[TEAM: confirm it was run]` |

---

## 6. Run-time AI — what the deployed system uses

The product itself calls LLMs and a vision model at query time. This is a designed feature,
not incidental, and every such call is disclosed:

| Stage | Model class | Purpose | Provenance guarantee |
|---|---|---|---|
| Ingestion (offline, cached) | Vision model via OpenRouter (`minimax/minimax-m3:free` measured; a fallback ladder behind it) | Describe the 70 figure images as label→value pairs + prose; OCR alone recovers 3/11 gold answers and 0 characters on 54/55 portraits (`docs/reports/ocr-vs-vlm.md`) | Descriptions stored in `data/index/images.jsonl`, served with a citation; `docs/decisions.md` ADR-002 |
| A1 Query Analyst | LLM (synthesis tier) | Intent classification, decomposition; vocabulary-only spell correction | Cannot override visual/contradiction routing |
| A3 Sufficiency Critic | LLM | Decide whether retrieved evidence answers the question | Must cite a verbatim quote per sub-question; validated, with a stop rule |
| A5 Answer Composer | LLM | Propose cited claims from an evidence block | Every quote resolved to a real span (`src/synthesis/citations.py`); retrieved text enters prompts only inside a delimited evidence block, never as instructions |
| A6 Verifier | LLM | Check each claim is entailed by its cited excerpts | Contradicted / unsupported claims are removed or downgraded to `inferred` |
| Embeddings / rerank | Local (`BAAI/bge-small-en-v1.5`, `Xenova/ms-marco-MiniLM-L-6-v2`) on CPU | Dense retrieval, reranking | No external call; a judge reproduces retrieval with no credentials (`docs/decisions.md` ADR-004) |

**The invented world is never composed from model priors.** `CLAUDE.md`: "Anything the
model 'knows' about the Ashen Era is hallucinated by definition. Compose only from
retrieved evidence." Groundedness is computed from the answer packet and reported.

---

## 7. What AI was explicitly NOT used for

- **Gold answer labels** (`eval/suites/*.json`) — hand-authored from the corpus;
  LLM-generated gold is forbidden in `.claude/agents/eval-engineer.md` ("grading a
  retriever with our own generator would be circular").
- **`data/corpus/`** — read-only; never modified, never regenerated.
- **ADR rationales** — the "what we rejected and why" blocks are human-written by design;
  `docs/decisions.md` carries a standing DRAFT NOTICE to that effect.
- **Git history** — `CLAUDE.md`: "Never fabricate history. We started late; judges check
  timestamps and can contact us." Commits are real and atomic across the working window;
  the compressed timeline is noted honestly in `docs/decisions.md`.
- **`[TEAM: anything else you want on record — e.g. the demo video narration, the final report prose]`**

---

## 8. This document and the evaluation report

`docs/reports/sample-questions-eval-2026-09-09.md` (the answer-level evaluation of the
20 dev questions + 8 unanswerable questions) and this disclosure file were produced in a
Claude Code session on 9 September 2026. The evaluation ran the team's own reasoning
service against the checked-in gold suites; the pass/fail grading and rating scale are
`[TEAM: review and endorse — or replace with your own human review scores]`.

---

*`[TEAM: sign-off — names, date. Remove all `[TEAM: …]` markers once resolved.]`*
