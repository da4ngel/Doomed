# Ashen Era Archive Assistant
#
# `make help` lists everything. The path a judge follows from a clean clone is:
#     make setup && make up && make ingest && make serve
#
# Every target is idempotent. Re-running ingest is cheap; re-running index is not
# (~20 min of CPU embedding), so it is a separate target on purpose.

.PHONY: help setup up down ingest images graph chunk index serve test lint fmt check \
        search ready ocr-report clean-index documents eval ablation gate record-baseline extract

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup

setup:  ## Install dependencies and unpack the corpus
	uv sync --all-groups
	@test -f .env || cp .env.example .env
	@test -d data/corpus/Ashen_Era_Archive || \
		uv run python -c "import zipfile; zipfile.ZipFile('data/corpus/Ashen_Era_Archive.zip').extractall('data/corpus')"
	@echo "setup complete - put your API keys in .env"

up:  ## Start Qdrant (Docker)
	docker compose up -d qdrant
	@echo "waiting for qdrant..."
	@until curl -s http://localhost:6333/readyz >/dev/null 2>&1; do sleep 2; done
	@echo "qdrant ready on :6333"

down:  ## Stop Qdrant
	docker compose down

# ---------------------------------------------------------------- build

ingest: images graph chunk  ## Full pipeline: documents, images, graph, chunks
	@echo "ingest complete - run 'make index' to build the search index"

documents:  ## Corpus -> documents.jsonl + blocks.jsonl (~20s)
	uv run python -m src.ingestion.pipeline

images:  ## Describe the 70 unique images with a vision model (cached)
	uv run python -m src.ingestion.images

graph:  ## Build the entity graph: wiki edges, then the recorded extracted ones
	uv run python -m src.graph.store --build
	uv run python -m src.graph.extract --apply-only

extract:  ## Re-derive the LLM edges from the corpus (needs a key; --apply-only does not)
	uv run python -m src.graph.extract --workers 3 --write

chunk: documents  ## Blocks -> chunks.jsonl
	uv run python -m src.ingestion.chunker

index:  ## Embed chunks into Qdrant + build BM25 (~20 min, CPU-bound)
	uv run python -m src.indexing.build

clean-index:  ## Drop the local embedded index
	rm -rf data/index/qdrant data/index/bm25

# ---------------------------------------------------------------- run

serve:  ## Start the API on :8000 (warms models at startup)
	uv run uvicorn src.api.main:app --port 8000

ready:  ## Show index counts and warm state
	@curl -s http://localhost:8000/v1/ready | uv run python -m json.tool

search:  ## Ad-hoc search: make search Q="Greyfell garrison strength"
	@curl -s -X POST http://localhost:8000/v1/search \
		-H 'content-type: application/json' \
		-d '{"query":"$(Q)","k":5}' | uv run python -m json.tool

# ---------------------------------------------------------------- checks

test:  ## Run the test suite (no Docker required)
	uv run pytest

lint:  ## ruff + black --check
	uv run ruff check src tests eval spikes scripts
	uv run black --check src tests eval spikes scripts

fmt:  ## Format in place
	uv run ruff check --fix src tests eval spikes scripts
	uv run black src tests eval spikes scripts

check: lint test  ## Lint and test

# ---------------------------------------------------------------- eval

eval:  ## Score the gold suites with the default config (needs a built index)
	uv run python -m eval.runner --suite all --failures

ablation:  ## Every retrieval config against every suite, into docs/reports/
	uv run python -m eval.runner --suite all --ablation \
		--out docs/reports/ablation-retrieval.json

gate:  ## Fail if any metric fell below eval/baseline.json
	uv run python -m eval.runner --suite all --ablation --gate

record-baseline:  ## Re-record eval/baseline.json - commit it with the change that moved it
	uv run python -m eval.runner --suite all --ablation --write-baseline \
		--out docs/reports/ablation-retrieval.json

ocr-report:  ## Measured Tesseract vs vision model comparison
	uv run python scripts/ocr_vs_vlm.py
