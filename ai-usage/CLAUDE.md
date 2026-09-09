# Ashen Era Archive Assistant

Competition RAG system over a 415-document, ~1,277-page invented fantasy archive.
SLIIT Codefest 2026 AI Competition, powered by IFS. Submission deadline:
**9 September 2026, 23:30.** Code freeze **9 September 12:00.**

**Thesis: sub-track 1B is the spine, 1C is its search-and-sufficiency loop, 1A is
its rich answer renderer.** One product, not three features.

## Prime rule

Every feature must produce evidence: a metric, a trace, a citation, a test result,
a decision record, or a demo moment. If it produces none of those, do not build it.

## Non-negotiables

- Python 3.11, uv, FastAPI, Pydantic v2. Type hints on all public functions.
- **NO LangChain, NO LlamaIndex.** We write orchestration ourselves. In the final
  round every member must be able to explain, justify and modify any part on demand.
  You can defend 400 lines of your own retrieval code. You cannot defend framework
  internals.
- Every external call goes through `core/retry.py` and `core/cache.py`. No exceptions.
  Free tiers return 429s; a system without backoff fails during demo recording.
- **The world is invented.** No public model has seen it. Anything the model "knows"
  about the Ashen Era is hallucinated by definition. Compose only from retrieved
  evidence.
- **Retrieved text always enters prompts inside a delimited evidence block, never in
  the instruction position.** The corpus contains in-world orders, decrees and trial
  transcripts — text that looks like instructions. Log suspicious spans and emit the
  `instruction_like_text_in_source` warning.
- `data/corpus/` is READ-ONLY.
- Secrets from env only. Never hard-code, never log, never print a key.
  `.env` is gitignored from commit #1.

## Frozen contracts

`Block`, `Chunk`, `Entity`, `Relation`, `Claim` and the answer packet are defined in
`src/api/schemas.py` and are FROZEN. Propose changes as an ADR before touching them.

`claims[]` with per-claim `citation_ids` **cannot be retrofitted** — groundedness is
computed from it as `count(claims where support != "inferred") / count(claims)`.

The seam between the knowledge layer and the reasoning layer is `POST /v1/search`.
P1 owns everything that produces evidence; P2 owns everything that consumes it.

## Authority tiers

| Tier | Class | Examples |
|---|---|---|
| 1 | Official reference | codex data books, figure plates, canonical tables |
| 2 | Encyclopaedic | wiki articles |
| 3 | Primary narrative | the four novel volumes |
| 4 | Primary record | letters, ledgers, trial transcripts |
| 5 | Unreliable / folkloric | ballads, tavern tales, in-world rumour |

Tier 4 is primary evidence but partial. Tier 5 is attested but unreliable. Sources
disagree, and surfacing the disagreement is a feature, not an error.

## Corpus facts (measured, not assumed)

Profiled 4 Sep from the real archive. Full numbers in `docs/corpus-profile.md`,
implications in `docs/corpus-findings.md`. These override any general assumption
about how a document corpus behaves.

- **341 files**, 1,248 actual PDF pages, ~1.44M tokens to embed (0.7% of the Voyage
  free allowance). Re-indexing is effectively free.
- **Dev-set track mix: 11x 1A, 7x 1B, 2x 1C.** 1A is likely over half the hidden set.
- **The 1A answers live inside images, not documents.** 85 PNGs in two classes:
  - `plate_*` (~30) — rendered text, Tesseract yields 71-153 clean chars
  - `atmo_*` (~55) — portraits, heraldry, creatures. **Tesseract yields ZERO chars.**
    A vision model is the only path to these marks.
- **There is a planted trap.** `plate_01_location_emberdeep.png` is a bar chart with
  800 / 2,400 / 6,000 reference values and **1,114** as the actual Emberdeep figure.
  Tesseract missed 1,114 entirely. Flat OCR + LLM answers 6,000. Figures require
  *understanding*, not text extraction. Index VLM structured description + OCR text
  + caption together.
- **Scan routing is a filename check**: all 17 scanned files are named `*.scan.pdf`.
  Only 41 pages need OCR. Keep the density heuristic as a fallback and report its
  agreement with the convention.
- **The wiki hands you the graph.** 95 markdown articles with `[[wikilinks]]` and
  Infobox tables (`Member of`, `Commands`, `Wields`, `Mentor of`, `Born`). Build the
  graph skeleton deterministically from these first — zero LLM cost, zero
  hallucination risk. Use LLM extraction only for `chronicles/` and `ephemera/`.
- **1C questions are contradiction questions.** Both dev 1C questions ask for the
  "true" / "actual" year. The A4 conflict layer is the 1C answer path, not a bonus.
- **`sample_questions.json` has no gold answers** — only qid, track, question. Every
  gold label is hand-authored from the corpus.

## Relation schema (read off the real dev questions and infoboxes)

`member_of · commands · wields · bore_since · mentor_of · born_in · ruled_by ·
located_in · lair_of · won · fought_in · allied_with · secret`

## Tier assignment — directory first, filename second

```python
def assign_tier(rel_path: str) -> tuple[int, str]:
    p = rel_path.lower().replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    if p.startswith(("codex/", "images/")) or "/plate_" in p or name.startswith("plate_"):
        return 1, "codex / official figure plate"
    if p.startswith("wiki/"):        return 2, "fan-wiki article"
    if p.startswith("chronicles/"):  return 3, "narrative novel"
    if p.startswith("ephemera/"):
        if name.startswith(("ballad", "sermon")):
            return 5, "folkloric / homiletic - unreliable narrator"
        return 4, "in-world primary record"
    return 4, "unknown provenance - flag for review"
```


## The runtime state machine

`A1 Query Analyst -> A2 Retrieval -> A3 Sufficiency Critic -> (loop | proceed)
 -> A4 Evidence Merger -> A5 Answer Composer -> A6 Verifier -> respond`

Specs in `skills/a1..a6-*.md`. Each file is simultaneously specification, prompt and
documentation. Read the spec before implementing; update it in the same commit as
any behaviour change.

These are bounded roles in an explicit state machine, not autonomous agents. Each has
a JSON output schema, a validator and a stop rule.

## Style

Small modules, one responsibility. Functions under 50 lines. Docstrings explain WHY,
not what. Tests alongside features. Any retrieval or chunking change requires an eval run.

## Definition of done

Code + test + docstring + recorded eval delta + conventional commit.

## Git

Conventional commits (`feat(retrieval): add RRF fusion with configurable k`). One
logical change per commit — never `git add .` on a day's work. Feature branch, PR,
reviewed by the other builder, merged without squashing.

**Never fabricate history.** We started late; judges check timestamps and can contact
us. Real atomic commits across the working window, and the compressed timeline noted
honestly in `docs/decisions.md`.

## Cut-line ladder

Cut in this order when behind, without renegotiating:
1. Debug page  2. Evidence-graph UI viz  3. Graph path-finding
4. Ablation configs 2, 3, 6  5. Streaming/SSE

**Never cut:** VLM figure description (it is over half the dev set), conflict
detection, `missing_information`, the eval harness, the Postman collection, the
README reproducibility path.
