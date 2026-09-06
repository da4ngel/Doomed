# Ashen Era Archive Assistant

An evidence-first RAG system over a 340-document invented fantasy archive, built for the
SLIIT Codefest 2026 AI Competition.

**Thesis: sub-track 1B is the spine, 1C is its search-and-sufficiency loop, 1A is its rich
answer renderer.** One product, not three features.

---

## The problem this archive actually poses

The corpus is deliberately adversarial, and most of the engineering here exists because of
three properties we measured rather than assumed (`docs/corpus-findings-addendum.md`):

1. **Over half the answers are not in the text.** 11 of the 20 dev questions are
   sub-track 1A, and their answers exist *only inside images*. Greyfell Citadel's garrison
   strength is **3,695**; that number appears in no document in the archive.

2. **The figures are booby-trapped.** `plate_01_location_emberdeep.png` is a bar chart
   with 800 / 2,400 / 6,000 printed as reference standards and **1,114** as Emberdeep's
   actual figure — drawn *shorter* than the 6,000 bar. Tesseract renders 1,114 as `Ee`.
   Flat OCR answers 6,000, and so does "read the biggest number" and "read the longest
   bar". Only binding each value to its own label gets it right.

3. **Near-miss names punish fuzzy matching.** `Greyfell Citadel` (3,695, image-only) sits
   beside `Ironfell Citadel` (1,096, in text). `The Thrice-Bound Edge` (94) sits beside
   `The Thrice-Bound Lantern` (55). A system that resolves one to the other returns a
   number that is fluent, plausible, and carries a *genuine citation to a real document* —
   the failure mode a reader cannot catch.

## Quick start

```bash
uv sync --all-groups
cp .env.example .env          # add OPENROUTER_API_KEY (and OPENAI_API_KEY if you have one)

# corpus is shipped zipped and is READ-ONLY
python -c "import zipfile; zipfile.ZipFile('data/corpus/Ashen_Era_Archive.zip').extractall('data/corpus')"

docker compose up -d qdrant

uv run python -m src.ingestion.pipeline     # ~20 s   documents -> blocks
uv run python -m src.ingestion.images       # ~3 min  70 images described (cached after)
uv run python -m src.graph.store --build    # ~2 s    wiki -> entity graph
uv run python -m src.ingestion.chunker      # ~10 s   blocks -> chunks
uv run python -m src.indexing.build         # ~20 min chunks -> Qdrant + BM25

uv run uvicorn src.api.main:app --port 8000
```

Only the last build step is slow — 2,474 chunks embedded on CPU at ~1.6/s. Everything before it is
fast enough to re-run freely. Full detail in **`docs/RUNBOOK.md`**.

## Verify it works

```bash
curl -s localhost:8000/v1/ready
# status: ready · warm: true
# documents 236 · chunks 2474 · images 70 · entities 198 · relations 379
```

```bash
curl -s -X POST localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query":"Greyfell Citadel recorded garrison strength","k":3}'
```

The top hit must be `plate_09_location_greyfell_citadel.png`. That answer exists only as
pixels — if you see it, the whole knowledge layer is working.

```bash
uv run pytest                    # 278 tests, no Docker or API keys required
npx newman run tests/postman/AshenEra.postman_collection.json \
    -e tests/postman/local.postman_environment.json     # 56 contract assertions
```

## Reproduce the numbers

Every figure in `docs/` comes from a command in this repo. With the index built:

```bash
uv run python -m eval.runner --suite all --ablation \
    --out docs/reports/ablation-retrieval.json     # the table in docs/reports/ablation.md

uv run python -m eval.runner --suite all --ablation --gate   # exits 1 on any drop

uv run python scripts/ocr_vs_vlm.py                # docs/reports/ocr-vs-vlm.md
```

The ablation reproduced byte-for-byte across two full runs, so `--gate` uses a 0.001
tolerance: a number that moves means behaviour changed. It refuses to score an empty
index rather than reporting 0.000 — that guard exists because a full run once printed a
table of zeros when the vectors were in a different Qdrant store.

What the numbers say, including where the system is weak, is in
**`docs/limitations.md`** — the answer layer is unmeasured, multi-hop coverage@10 is
0.429, and reranking makes multi-hop retrieval worse.

## Architecture

```
corpus (READ-ONLY)
   │
   ├── ingestion ──► 236 logical documents ──► 3,095 blocks ──► 2,444 chunks
   │                 (format twins collapsed)   (tables atomic, page + bbox)
   │
   ├── images ─────► 70 described (VLM)  ──► label→value pairs, entity-linked
   │
   ├── graph ──────► 203 entities, 379 relations, every edge citing its source
   │
   └── indexing ───► Qdrant (dense) + BM25 (sparse)
                         │
                    POST /v1/search  ◄── the frozen seam
                         │
                    agents A1–A6 ──► POST /v1/chat ──► answer packet
```

**The seam is `POST /v1/search`.** Everything above it produces evidence; everything below
consumes it. That boundary is what lets two people build in parallel — see
`docs/WORKSPLIT.md`.

## Endpoints

| | |
|---|---|
| `GET /v1/health` `GET /v1/ready` | liveness; index counts and warm state |
| `POST /v1/search` | dense / sparse / hybrid, rerank, tier + source filters |
| `POST /v1/graph/neighbors` `POST /v1/graph/paths` | k-hop expansion and hop chains, every edge sourced |
| `GET /v1/assets/{id}` `GET /v1/assets/{id}/meta` | figure bytes; structured description with label→value pairs |
| `GET /v1/metrics` | cache hit rate, cost |

Interactive docs at `http://localhost:8000/docs`.

## Design decisions worth knowing

Full records in `docs/decisions.md`. The load-bearing ones:

- **No orchestration framework** (ADR-001). Every member must be able to explain and
  modify any part under questioning in the final round.
- **Vision model for figures, measured not assumed** (ADR-002). `minimax/minimax-m3:free`
  reads the Emberdeep trap correctly at **$0.00**; the spike result and the four defects it
  exposed are recorded.
- **Authority tiers assigned directory-first** (ADR-003). The filename rules left 87 of 340
  files unclassified; directory-first leaves zero. Tier drives conflict resolution, and a
  confidently mis-resolved conflict is a fabrication with a citation attached.
- **Local-first embeddings** (ADR-004). No Voyage key, so BGE-small runs on CPU — and a
  judge reproduces retrieval with no credentials at all.
- **Chunk size derived from the model's context window** (ADR-008). A round 600-token
  target left 173 chunks (8.8%) indexed but only partly embedded — present in the store,
  unreachable by dense retrieval, with no error to notice.

## Repository layout

```
src/ingestion/    adapters, OCR, images, pairing, chunker, tiers
src/indexing/     embeddings, Qdrant, BM25
src/retrieval/    hybrid search, RRF fusion, rerank
src/graph/        wiki extraction, SQLite store, traversal
src/agents/       A1–A6 (in progress)
src/api/          FastAPI app, frozen schemas, routes
eval/suites/      hand-authored gold sets
skills/           A1–A6 specifications (spec = prompt = documentation)
docs/             findings, decisions, runbook, work split
tests/            202 unit + integration, Postman collection
```

## Status

**Knowledge layer complete and measured.** Gold recovery 11/11 on the 1A dev questions;
all three 1B hop chains resolve with evidence; 278 tests; retrieval gated against a
recorded baseline.

**Reasoning layer in progress** — agents, `/v1/chat` and the UI, see
`docs/P2-HANDBOOK.md`. Until it lands, no answer-level metric in this repo has been
produced from a real answer, and `docs/limitations.md` says so first rather than last.
