# Runbook — how to run and test the system

Two entry points. `make` on Linux/macOS/CI; the plain commands on Windows, where `make`
is usually absent (install with `winget install ezwinports.make` if you want it).

## One-time setup

```bash
uv sync --all-groups
cp .env.example .env          # then add OPENROUTER_API_KEY / OPENAI_API_KEY
```

## Start the vector store

```bash
docker compose up -d qdrant
curl http://localhost:6333/readyz          # -> "all shards are ready"
```

Qdrant also runs **embedded**, as a local file, when `QDRANT_URL` is unset — that is how
the test suite and CI run, so neither needs Docker. Set `QDRANT_URL=http://localhost:6333`
in `.env` to use the service.

## Build the knowledge base

| Step | Command | Time |
|---|---|---|
| Documents → blocks | `uv run python -m src.ingestion.pipeline` | ~20 s |
| Images → descriptions | `uv run python -m src.ingestion.images` | ~3 min (cached after) |
| Wiki → entity graph | `uv run python -m src.graph.store --build` | ~2 s |
| Blocks → chunks | `uv run python -m src.ingestion.chunker` | ~10 s |
| Chunks → search index | `uv run python -m src.indexing.build` | **~20 min** |

Only the last step is slow: 2,444 chunks embedded on CPU at ~2/sec. Everything before it
is fast enough to re-run freely.

**Switching between embedded and Docker requires re-running `src.indexing.build`** — the
vectors live in whichever store was written, they do not transfer.

## Run it

```bash
uv run uvicorn src.api.main:app --port 8000
```

The API warms its models at startup, so the first request is ~1.1 s rather than ~31 s.

```bash
curl -s localhost:8000/v1/ready | python -m json.tool
```

Expect `status: ready`, `warm: true`, and:
`documents 236 · chunks 2444 · images 70 · entities 203 · relations 379`

## The two searches that prove it works

Both target planted traps in the corpus.

```bash
curl -s -X POST localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query":"Greyfell Citadel recorded garrison strength","k":3}'
```
Rank 1 must be `plate_09_location_greyfell_citadel.png`. That answer (**3,695**) exists
**only inside the image** — it appears in no document in the archive. The decoy
`Ironfell Citadel` should appear below it, not above.

```bash
curl -s -X POST localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query":"Thrice-Bound Lantern attunement cost","k":2}'
```
Rank 1 must be the **Lantern** plate (55), rank 2 the **Edge** plate (94). The two names
differ by one token and dense similarity pulls them together; BM25 separates them.

## Tests

```bash
uv run pytest          # 188 tests, no Docker needed
uv run ruff check src tests
```

Tests never touch the Docker service and never require API keys. Anything needing the
corpus skips cleanly when `data/corpus/` is absent.

## Interactive API docs

`http://localhost:8000/docs` — the OpenAPI schema Postman imports from
`http://localhost:8000/openapi.json`.
