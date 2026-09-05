# Scaffold — drop-in for the Ashen Era repo

Copy the contents of this folder into your repo root on D0.

```
CLAUDE.md                    → repo root
.claude/agents/*.md          → 8 build subagents
.claude/commands/*.md        → 3 slash commands
skills/a1..a6-*.md           → 6 runtime agent specs
scripts/profile_corpus.py    → the D0 gate deliverable
```

Then mirror the instruction files into the submission folder the competition asks for:

```bash
mkdir -p ai_usage/skills
cp -r .claude/agents .claude/skills skills/* ai_usage/skills/ 2>/dev/null
cp CLAUDE.md ai_usage/claude.md
```

---

## 1. Run the profiler first

This is the one task that unblocks every ingestion decision.

```bash
uv add pymupdf python-docx pillow
python scripts/profile_corpus.py --corpus data/corpus --out docs
```

Outputs `docs/corpus-profile.md` and `docs/corpus-profile.json`.

| Flag | Use |
|---|---|
| `--tables` | run PDF table detection. Accurate, slow on ~1,300 pages. Leave off for the first pass, run overnight |
| `--sample 50` | profile the first 50 files only, for a fast sanity check |

**Read the "Ingestion verdict" section first.** It converts the scanned-page ratio
into a concrete instruction for how Saturday should be spent. The four bands are
low (<5%), moderate (5–20%), high (20–50%), dominant (>50%), and they change the
shape of D1, not just its length.

Three other things to act on immediately:

- **The tier table is a guess.** It is pattern-matched from filenames and paths.
  Review it and fix the rules in `src/ingestion/tiers.py` before D1 ends. Tier drives
  conflict resolution in agent A4 — a wrong tier table produces confidently wrong
  conflict outcomes, which is worse than no conflict layer at all.
- **The dead-letter preview** lists files that broke the profiler. They will break
  ingestion too. This is the concrete argument for a dead-letter list instead of a
  hard failure.
- **The OCR-heavy file list** is your parser test fixture set. If ingestion handles
  those, it handles the corpus.

The headline table belongs on page 2 of the submission report. *"We profiled the
corpus before designing ingestion"* is **Problem understanding & insight** (15%), and
those numbers are what prove it rather than assert it.

The tunable constants at the top of the script (`SCANNED_CHAR_THRESHOLD`,
`SPARSE_CHAR_THRESHOLD`, `FULLPAGE_IMAGE_COVERAGE`) are the same heuristics ingestion
will use. Import them from one place rather than duplicating the numbers.

---

## 2. The eight build subagents

In `.claude/agents/`. Claude Code delegates to these automatically based on their
`description` field, or you can invoke one by name.

| Subagent | Owns |
|---|---|
| `ingestion-engineer` | `src/ingestion/` — adapters, OCR, figures, chunker |
| `retrieval-engineer` | `src/indexing/`, `src/retrieval/` — embeddings, hybrid, rerank |
| `graph-engineer` | `src/graph/` — entities, canonicalisation, traversal |
| `agent-engineer` | `src/agents/`, `src/synthesis/` — the state machine, A1–A6 |
| `eval-engineer` | `eval/` — metrics, ablation harness, regression gate |
| `api-contract-engineer` | `src/api/`, `tests/postman/`, `.github/` |
| `docs-scribe` | `docs/`, `README.md` |
| `adversarial-reviewer` | read-only; reviews diffs and red-teams the API |

Two of these carry a constraint that is the entire point of the role:

**`eval-engineer` must not read implementation code before writing a metric.** It
implements from `docs/evaluation.md` only. If it reads the retriever first, it will
write metrics that pass the code that already exists — which makes every number in
your report meaningless and is exactly what a sharp judge probes for.

**`docs-scribe` must not write the rationale in an ADR.** It scaffolds Context,
Options and Consequences; the human writes "what we rejected and why". Human–AI
collaboration is 15% of the score and is assessed from these documents. Generated
rationale is worse than none, because it reads as one-shot generation.

**Run `adversarial-reviewer` at the end of every working day.** Its output feeds
`docs/limitations.md` and the interrogation drill. It is the cheapest insurance you
can buy against the final round, where every member must explain and modify any part
on demand.

---

## 3. The three slash commands

| Command | Does |
|---|---|
| `/adr <title>` | scaffolds the next numbered ADR with the three human blocks left as TODO |
| `/eval [suite] [--ablation]` | runs a suite, diffs against baseline, prints the failure taxonomy distribution and the five worst questions |
| `/ingest-test [N]` | re-ingests N documents to a scratch index and smoke-tests retrieval in under 90 seconds |

`/eval` prints the failure taxonomy split, not just the score. A drop in `synthesis`
failures with flat `retrieval` failures means the prompt improved; the reverse means
the index did. That distinction is what stops you optimising the wrong layer.

---

## 4. The six runtime agent specs

In `skills/`. Each file is **specification, prompt, and documentation at once** —
write the prompt from the spec, and update the spec in the same commit as any
behaviour change. They also satisfy the `ai_usage/skills` folder the competition
structure asks for.

```
A1 Query Analyst  →  A2 Retrieval  →  A3 Sufficiency Critic  →  (loop | proceed)
                          ↑_________________|
   →  A4 Evidence Merger  →  A5 Answer Composer  →  A6 Verifier  →  respond
```

Each has an input schema, an output schema, ordered steps, stop rules, a failure
fallback table, and tests. They are bounded roles in a state machine, not autonomous
agents — say exactly that when a judge asks whether the system is agentic.

The three that carry the most score:

- **A3 Sufficiency Critic** is sub-track 1C. Its test that matters:
  `next_query` on a multi-hop question must contain a term that first appeared in the
  *previous* step's results. That is what separates reasoning from rephrasing, and
  it is what `gain_per_step` measures.
- **A4 Evidence Merger** is differentiator #1. When two equal-tier sources conflict
  it must return `resolution: "unresolved"` and surface both, rather than picking.
  Refusing to resolve is the feature.
- **A6 Verifier** is what turns "we prompt carefully" into "we check". Removing a bad
  claim always beats shipping it — in a corpus no model has seen, one fabricated
  citation makes a judge distrust every number in your report.

---

## 5. Notes

- Claude Code's config format changes between versions. If a subagent or command
  doesn't load, check the current frontmatter fields in the docs — the *content* of
  these files is what matters and transfers regardless of the wrapper.
- `CLAUDE.md` includes the frozen contracts and the cut-line ladder. When you're
  behind at 2am, the ladder is there so you don't have to make scope decisions tired.
- The profiler is standalone with no repo dependencies. Run it tonight, before any
  other code exists.
