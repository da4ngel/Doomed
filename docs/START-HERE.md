# START HERE — tonight, in order

You have six artifacts and one evening. This is the sequence.

---

## 0. Where everything goes

| Artifact | Destination | Purpose |
|---|---|---|
| `ashen-scaffold.zip` | unzip into repo root | `CLAUDE.md`, 8 subagents, 3 commands, 6 agent specs, profiler |
| `codefest-2026-master-plan.md` | `docs/master-plan.md` | the plan. Reference, not context to paste |
| `corpus-findings.md` | `docs/corpus-findings.md` | **overrides the master plan where they disagree** |
| `corpus-profile.md` / `.json` | `docs/` | D0 gate deliverable — but regenerate on your own machine |
| `Ashen_Era_Archive.zip` | `data/corpus/` | gitignored, read-only |
| plan v1, plan v2 | delete | superseded |

**Precedence rule.** `CLAUDE.md` > `docs/corpus-findings.md` > `docs/master-plan.md`.
The findings are measured from the real corpus; the plan was written before it existed.
Add this line to the top of `docs/master-plan.md` so nobody gets confused on day three.

---

## 1. Repo, gitignore first (10 min)

`.gitignore` before anything else. The corpus is 123MB and your keys are one careless
`git add .` from being permanently in history.

```bash
mkdir ashen-era-assistant && cd ashen-era-assistant
git init && git branch -M main

cat > .gitignore << 'EOF'
.env
.env.local
data/corpus/
data/assets/
data/index/
data/cache/
*.db
*.sqlite
*.sqlite3
__pycache__/
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
node_modules/
dist/
*.log
.DS_Store
EOF

cat > .env.example << 'EOF'
# names only, never real values
OPENROUTER_API_KEY=
VOYAGE_API_KEY=
QDRANT_URL=http://localhost:6333
LLM_MODEL_SYNTHESIS=deepseek/deepseek-chat
LLM_MODEL_CHEAP=
LLM_MODEL_VISION=
EOF

git add .gitignore .env.example
git commit -m "chore: initialise repository with secret and corpus exclusions"
```

Unzip the scaffold into the root, drop the docs in, and put the corpus in place:

```bash
unzip -o ~/Downloads/ashen-scaffold.zip -d /tmp/s && cp -r /tmp/s/ashen-scaffold/. .
mkdir -p docs data/corpus
cp ~/Downloads/codefest-2026-master-plan.md docs/master-plan.md
cp ~/Downloads/corpus-findings.md docs/
unzip -q ~/Downloads/Ashen_Era_Archive.zip -d data/corpus

git add CLAUDE.md .claude skills scripts docs SCAFFOLD-README.md
git commit -m "docs: add build plan, corpus findings, agent specs and Claude Code config"
```

---

## 2. Regenerate the profile on your machine (10 min)

You have my output, but the repo needs one you produced — it must be reproducible, and
a judge may re-run it.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv init --name ashen-era-assistant --python 3.11
uv add pymupdf python-docx pillow pytesseract

uv run python scripts/profile_corpus.py --corpus data/corpus/Ashen_Era_Archive --out docs
git add docs/corpus-profile.* pyproject.toml uv.lock
git commit -m "feat(profiling): profile corpus - 341 files, 1248 PDF pages, 5.5% needing OCR"
```

Expected: 341 files, 1,248 PDF pages, 69 needing OCR (5.5%). If your numbers differ,
stop and find out why before building on them.

---

## 3. The VLM spike — do this tonight, before anything else is built (30 min)

**This is the highest-value 30 minutes of your week.** Finding 1 says over half the dev
set is answerable only from images, and the Emberdeep plate is a chart where flat OCR
gives a confident wrong answer. If free vision models cannot read that chart, your
entire 1A approach needs to change — and you need to know that on Friday, not Sunday.

Get an OpenRouter key, then:

```bash
mkdir -p spikes
uv add httpx
```

Ask Claude Code (see prompt 3 below) to write `spikes/vlm_plate_spike.py` that sends
three images to a free vision model on OpenRouter and prints what comes back:

| Image | Correct answer | What failure looks like |
|---|---|---|
| `images/plate_01_location_emberdeep.png` | **1,114** | returns 6,000 or 800 — the chart trap |
| `images/plate_09_location_greyfell_citadel.png` | **3,695** | easy case, should pass |
| `wiki/images/atmo_portrait_character_ignatz_ashgrove_the_oathless.png` | a rolled scroll | returns a generic description with no object named |

**Decision gate.** If a free model gets Emberdeep right, the plan holds. If it fails,
try two more free vision models, then a paid one (cents per image — 85 images total).
If nothing reads charts reliably, fall back to: OCR + spatial layout from bounding
boxes, feeding the LLM "label at (x,y) = value at (x,y)" pairs instead of flat text.

Whatever you find, write it up as ADR-002 tonight. A spike with a recorded result is
exactly the "human decisions clearly visible" the rubric asks for.

---

## 4. The first three Claude Code sessions

Run `claude` in the repo root. `CLAUDE.md` loads automatically — **do not paste the
master plan into context.** Point sessions at specific files instead.

Keep sessions short and topical. One component each, commit at the end. Long omnibus
sessions read as one-shot generation in the exported logs and cost you 15%.

### Session 1 — P2 — freeze the schemas

> Read `CLAUDE.md` and section 2.4 of `docs/master-plan.md`. Implement
> `src/api/schemas.py` with Pydantic v2 models for Document, Block, Chunk, Entity,
> Relation, Claim and the full answer packet. Before writing code, list anything in
> that schema you think is wrong or under-specified and wait for my response. These
> models are frozen after this session, so raise objections now.

### Session 2 — P2 — the core wrappers

> Implement `src/core/retry.py` (exponential backoff 1s/2s/4s/8s over HTTP 429 and
> 5xx, with a circuit breaker), `src/core/cache.py` (SQLite keyed on
> `sha256(model + prompt + params)`), and `src/core/trace.py` (persist every agent step
> and usage record). Every external call in this project goes through these. Write the
> tests first. Do not touch `schemas.py`.

### Session 3 — P1 — the VLM spike

> Read the "Corpus facts" section of `CLAUDE.md`. Write `spikes/vlm_plate_spike.py`
> that sends three images to a free vision model on OpenRouter and prints the raw
> response plus whether the expected value appears: emberdeep plate expects 1,114,
> greyfell plate expects 3,695, ignatz portrait expects a scroll. Use `core/retry.py`.
> Print the model name, tokens and cost per image. Do not build a pipeline — this is a
> throwaway spike to answer one question.

Then, tomorrow morning, use the subagents by name: `ingestion-engineer` for parsers,
`retrieval-engineer` for the index, and so on. `/adr` after every real decision.

---

## 5. Who does what tonight

| Who | Tonight |
|---|---|
| **You (P1)** | Steps 1–3. The VLM spike is yours; it de-risks the biggest finding |
| **P2** | Sessions 1 and 2. `docker-compose.yml` with qdrant + api. `/v1/health` returning green |
| **M3** | Start the gold set. Do the **11 `plate_*` questions first** — open the image, read the number, write the answer. Quick wins that unblock the `chart_reading` eval suite |
| **M4** | Open `docs/decisions.md`. Write ADR-000 (1B spine / 1C loop / 1A renderer) and ADR-001 (no framework) from the master plan's reasoning. Set up the AI log export script |

All four: create OpenRouter accounts and keys tonight. One of you adds a card to Voyage.
Four keys means 200 free requests a day for development instead of 50.

---

## 6. D0 exit gate

Do not go to bed until all of these are true:

- [ ] `.gitignore` committed before any other file
- [ ] `docs/corpus-profile.md` regenerated on your machine, numbers match
- [ ] `src/api/schemas.py` frozen and committed
- [ ] `core/retry.py` and `core/cache.py` exist and are tested
- [ ] `/v1/health` returns 200
- [ ] VLM spike run, result recorded as ADR-002
- [ ] 10+ real commits on `main`
- [ ] M3 has at least 11 gold labels written
- [ ] `git log --oneline` reads like a team working, not one person dumping

---

## 7. Tomorrow (D1)

**P1's morning is the image pipeline**, not PDF parsing. That is the change the corpus
findings forced: 85 images, bounded and high-value, carrying more than half the dev set.
Describe every one with the VLM, OCR the `plate_*` set, index description + OCR text +
caption together, cache all of it. PDF and DOCX parsing comes after.

**P2's morning is `/v1/search` returning fixtures**, so the whole answer path is
exercised end-to-end before real retrieval exists.

The rest of D1 is in `docs/master-plan.md` §5.3 — read it with `docs/corpus-findings.md`
open beside it.
