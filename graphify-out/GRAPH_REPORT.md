# Graph Report - src  (2026-09-09)

## Corpus Check
- Corpus is ~44,766 words - fits in a single context window. You may not need a graph.

## Summary
- 914 nodes · 1786 edges · 66 communities (44 shown, 12 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 344 edges (avg confidence: 0.91)
- Token cost: 112,052 input · 0 output

## Community Hubs (Navigation)
- Answer Composition (A5)
- Conflict Adaptation
- Agent Wiring
- OCR Extraction
- Query Analysis (A1)
- Block and Chunk Contracts
- Format Adapters
- Tracing and Usage
- Retry and Circuit Breaking
- Vocabulary Loading
- Frozen API Schemas
- Image Description
- Retrieval Seam and Expansion
- Settings and Configuration
- LLM Providers
- Wiki Graph Extraction
- Indexing Qdrant
- API Main
- API Routes
- Agents Analyst
- Indexing Bm25
- Indexing Embed
- API Routes
- Retrieval Expand
- Core Evidence
- External Types 25
- External Types 26
- External Types 27
- External Types 28
- External Types 29
- API Routes
- Core Llm
- Indexing Embed
- External Types 33
- Core Llm
- Graph Store
- Retrieval Rrf
- External Types 37
- External Types 38
- External Types 39
- Core Llm
- External Types 41
- External Types 42
- External Types 43
- External Types 44
- Synthesis Prompts
- External Types 46
- External Types 47
- External Types 57
- External Types 58
- External Types 59
- External Types 60
- External Types 61
- External Types 62
- External Types 63
- External Types 64

## God Nodes (most connected - your core abstractions)
1. `Frozen` - 49 edges
2. `Settings` - 40 edges
3. `Orchestrator` - 32 edges
4. `get_settings()` - 32 edges
5. `SearchHit` - 29 edges
6. `TraceStore` - 27 edges
7. `GraphStore` - 27 edges
8. `Entity` - 25 edges
9. `Warning` - 25 edges
10. `AnswerPacket` - 25 edges

## Surprising Connections (you probably didn't know these)
- `_load_entities()` --uses--> `Entity`  [INFERRED]
  agents/analyst.py → api/schemas.py
- `_load_entities()` --calls--> `get_settings()`  [INFERRED]
  agents/analyst.py → core/config.py
- `_load_entities()` --uses--> `RetryPolicy`  [INFERRED]
  agents/analyst.py → core/retry.py
- `_names()` --uses--> `Entity`  [INFERRED]
  agents/analyst.py → api/schemas.py
- `_mentions()` --uses--> `Entity`  [INFERRED]
  agents/analyst.py → api/schemas.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **A1-A6 Reasoning State Machine** — src_agents_readme_a1_query_analyst, src_agents_readme_a2_retrieval, src_agents_readme_a3_sufficiency_critic, src_agents_readme_a4_evidence_merger, src_agents_readme_a5_answer_composer, src_agents_readme_a6_verifier, src_agents_readme_orchestrator [EXTRACTED 1.00]
- **Three P1 Integration Defects Triaged 7 September** — src_agents_upstream_issues_embedded_qdrant_readiness_issue, src_agents_upstream_issues_mournwatch_conflict, src_agents_upstream_issues_rebuild_count_diff_issue [EXTRACTED 1.00]
- **Ederon Fellgard Multi-Hop Trajectory (1b_007)** — src_agents_live_validation_1b_007_question, src_agents_live_validation_ederon_fellgard, src_agents_live_validation_iron_ring_cartel, src_agents_live_validation_leaden_accord [EXTRACTED 1.00]

## Communities (66 total, 12 thin omitted)

### Community 0 - "Answer Composition (A5)"
Cohesion: 0.06
Nodes (53): AnswerComposer, _is_table(), _portrait_quotes(), AnswerMode, A5 proposes cited claims; IDs, metadata and accepted visuals are code-…, Duplicate excerpts do not establish independent corroboration., Include the indexed portrait caption when its description omits the subject…, _support() (+45 more)

### Community 1 - "Conflict Adaptation"
Cohesion: 0.06
Nodes (41): ConflictAdapter, Connect P1's real A4 ABI without importing the graph or altering source text., A1 and A4 share one complete, validated HTTP vocabulary per request., Vocabulary, Entity, No unsourced edges, ever. ``evidence_chunk_id`` is required, not optional., Relation, build_prompt() (+33 more)

### Community 2 - "Agent Wiring"
Cohesion: 0.06
Nodes (39): BoundedLLM, Budget, BudgetExceeded, CompletionClient, _GuardedProvider, KnowledgeClient, Any, Protocol (+31 more)

### Community 3 - "OCR Extraction"
Cohesion: 0.05
Nodes (51): ocr_image(), OcrResult, Path, Tesseract OCR, with graceful absence. WHY it degrades instead of raising:…, Outcome of one OCR attempt. `available=False` means Tesseract is not installed…, True when the binary is on PATH or at the standard Windows install location., Version string for the report, or None when unavailable., Run OCR over one image. Never raises. (+43 more)

### Community 4 - "Query Analysis (A1)"
Cohesion: 0.10
Nodes (28): Analysis, QueryAnalyst, Single-pass A1; injected vocabulary/LLM make offline behavior reproducible. No…, focused_chunks(), Select visual evidence by exact linked subject while preserving raw retrieval…, Figure source identity is stronger than incidental mentions inside its…, Coverage, Critique (+20 more)

### Community 5 - "Block and Chunk Contracts"
Cohesion: 0.08
Nodes (42): Block, Chunk, The atomic unit of extraction. For figures, ``text`` holds the VLM description…, _encoding(), estimate_tokens(), One token counter, shared by ingestion and the reasoning runtime. WHY it lives…, Token count via tiktoken when available, else a 4-chars-per-token estimate. The…, chunk_document() (+34 more)

### Community 6 - "Format Adapters"
Cohesion: 0.06
Nodes (42): BlockType, Counter, block_checksum(), clean_text(), is_caption(), make_block(), Shared helpers for the format adapters. Every adapter returns `list[Block]`…, Collapse runs of spaces and blank lines without destroying paragraph breaks. (+34 more)

### Community 7 - "Tracing and Usage"
Cohesion: 0.07
Nodes (24): Rendered live in the trace panel. ``learned`` and ``missing`` are what make the…, TraceStep, UsageRecord, new_trace_id(), Connection, Path, Reasoning trace persistence — every agent step, recorded as it happens. WHY…, Append one agent step. Written immediately rather than batched at the end, so… (+16 more)

### Community 8 - "Retry and Circuit Breaking"
Cohesion: 0.09
Nodes (21): BaseException, Run one completion, falling back through providers on failure. `provider` pins…, call_with_retry(), CircuitBreaker, CircuitOpenError, _is_retryable(), Exception, Exponential backoff and a circuit breaker for every outbound call. WHY: the… (+13 more)

### Community 9 - "Vocabulary Loading"
Cohesion: 0.13
Nodes (14): _load_entities(), One HTTP attempt; retry infrastructure honors A1's no-retry stop rule., BaseTransport, cache_key(), Any, Connection, Path, SQLite response cache keyed on sha256(model + prompt + params). WHY: two… (+6 more)

### Community 10 - "Frozen API Schemas"
Cohesion: 0.13
Nodes (23): Citation, Claim, Conflict, Document, EntityVocabularyResponse, EvidenceGraph, Frozen, GraphEdge (+15 more)

### Community 11 - "Image Description"
Cohesion: 0.16
Nodes (22): build_wiki_image_index(), _canonical(), caption_and_entity(), describe_one(), discover_images(), ImageRecord, main(), print_stats() (+14 more)

### Community 12 - "Retrieval Seam and Expansion"
Cohesion: 0.15
Nodes (15): SearchRequest, SearchResponse, Expansion, Neighbouring chunks from the same document and section as each hit. Bounded by…, What expansion added, and why — so a trace can show its working., section_expand(), _hit_from_metadata(), The retrieval pipeline behind POST /v1/search. Each stage is independently… (+7 more)

### Community 13 - "Settings and Configuration"
Cohesion: 0.13
Nodes (12): BaseSettings, Path, Runtime settings, populated from the environment and `.env`., Which providers have credentials — names only, never values., Loggable view of the config. Secrets appear as booleans, never as values., Settings, GeminiProvider, OpenAIProvider (+4 more)

### Community 14 - "LLM Providers"
Cohesion: 0.16
Nodes (14): _cost(), image_part(), Any, Path, Response, raise_with_body(), One LLM interface, three thin provider adapters, with a fallback chain. WHY a…, Build a message part carrying an image, as a base64 data URI. (+6 more)

### Community 15 - "Wiki Graph Extraction"
Cohesion: 0.15
Nodes (19): EntityType, _clean(), entity_id(), extract(), ExtractionReport, _infer_type(), load_corpus_articles(), parse_article() (+11 more)

### Community 16 - "Indexing Qdrant"
Cohesion: 0.13
Nodes (10): point_id(), Exception, RuntimeError, QdrantStore, QdrantUnavailableError, Qdrant vector store, one code path for the Docker service and the embedded…, Return (chunk_id, score, payload), best first., Deterministic point id for a chunk. Stable across runs, unique across batches. (+2 more)

### Community 17 - "API Main"
Cohesion: 0.15
Nodes (18): _count_jsonl(), _count_table(), health(), lifespan(), metrics(), openapi_json(), FastAPI, get (+10 more)

### Community 18 - "API Routes"
Cohesion: 0.16
Nodes (17): _edge_out(), entities(), get_store(), neighbors(), paths(), get, post, POST /v1/graph/neighbors and /v1/graph/paths — sub-track 1B's evidence source.… (+9 more)

### Community 19 - "Agents Analyst"
Cohesion: 0.24
Nodes (14): Correction, _corrections(), _intent(), _matching_text(), _mentions(), _names(), _non_overlapping(), Plan (+6 more)

### Community 20 - "Indexing Bm25"
Cohesion: 0.20
Nodes (7): SearchFilters, BM25Store, BM25 sparse index over the same chunks. WHY sparse matters here more than in a…, Every chunk id in index order, which is document order. Section expansion needs…, Lowercase word tokens, keeping hyphens and apostrophes. `thrice-bound` must…, True only when a filter would actually exclude something. WHY this is not `if…, tokenize()

### Community 21 - "Indexing Embed"
Cohesion: 0.16
Nodes (11): get_settings(), Central configuration. WHY this exists: CLAUDE.md forbids hard-coded secrets…, load_chunks(), main(), Build the dense and sparse indexes from chunks.jsonl. Both indexes are built in…, Embedder, get_embedder(), model_cache_dir() (+3 more)

### Community 22 - "API Routes"
Cohesion: 0.23
Nodes (12): get_asset(), get_asset_meta(), list_assets(), FileResponse, get, GET /v1/assets/{id} and /v1/assets/{id}/meta — serving the figures. WHY this…, asset_id -> record, loaded once from images.jsonl., Stream the image itself, straight from the read-only corpus. (+4 more)

### Community 23 - "Retrieval Expand"
Cohesion: 0.21
Nodes (11): build_doc_chunks(), doc_slug(), entities_in_query(), graph_expand(), _normalise(), Context expansion — ablation rows 5 and 6. Two different jobs that are easy to…, `wiki/the_purge_of_blackport.md` -> `the_purge_of_blackport`. The graph records…, Entities whose canonical name appears verbatim in the query. Longest name… (+3 more)

### Community 24 - "Core Evidence"
Cohesion: 0.24
Nodes (8): EvidenceBlock, find_instruction_like(), Put retrieved corpus text into a prompt without letting it act as a prompt.…, A prompt-safe rendering of one or more retrieved passages., Warning codes for the answer packet. Empty when nothing was flagged., Every span in `text` that reads as an instruction, with why it was flagged.…, Render `(source_id, text)` pairs as one delimited, labelled evidence block.…, render()

### Community 25 - "External Types 25"
Cohesion: 0.22
Nodes (9): A5 Answer Composer, A6 Verifier, AnswerPacket (frozen schema), ChatRequest (frozen schema), GET /v1/traces/{id}, POST /v1/chat, POST /v1/chat/jobs, tool_failure / verification_skipped warning (+1 more)

### Community 26 - "External Types 26"
Cohesion: 0.29
Nodes (7): Emberdeep case (1,114, reference bars trap), Greyfell case (3,695 from its own plate), Thrice-Bound Edge case (94, plate/wiki disagreement), Diagnostic progression table (DeepSeek to free-model runs), Numeric/extractive candidate guard (survive partial investigation), Gauntlet run (unknown forging date, false complete flag), Structural fix over confidence threshold (confident misread insight)

### Community 27 - "External Types 27"
Cohesion: 0.29
Nodes (7): 1a_001 question (apostrophe variant), prior A1 commit d247c82, A1 Query Analyst, ASHEN_SAMPLE_QUESTIONS env var, Bounded Orchestrator / State Machine, sample_questions.json gold suites, Track 1C contradiction routing

### Community 28 - "External Types 28"
Cohesion: 0.33
Nodes (7): A2 Retrieval Agent, A3 Sufficiency Critic, Conservative token reservation design, Deadline-bound LLM/HTTP waiting, Deep Semantic Search mode, list_mentions tool, read_section tool (does not exist)

### Community 29 - "External Types 29"
Cohesion: 0.29
Nodes (7): EntityVocabularyResponse, GET /v1/graph/entities, normalization_skipped warning, MergeReport.extraction_disagreements, data/index/images.jsonl, Mournwatch OCR/VLM conflict (8,254 vs 6,254), test_every_conflict_names_two_real_sources

### Community 30 - "API Routes"
Cohesion: 0.40
Nodes (5): get_retriever(), post, POST /v1/search — THE SEAM. This endpoint and the…, Retrieval primitive: dense, sparse or hybrid, with optional rerank and filters., search()

### Community 33 - "External Types 33"
Cohesion: 0.33
Nodes (6): Open gates (remaining blockers), Embedded Qdrant readiness issue, get_retriever().vectors fix, GET /v1/ready, QdrantStore, test_readiness_survives_a_real_search

### Community 34 - "Core Llm"
Cohesion: 0.40
Nodes (3): LLMClient, Facade over the providers: cache, then retry, then fallback, then usage., Full message content, images included, so two different images never collide.

### Community 35 - "Graph Store"
Cohesion: 0.50
Nodes (4): build(), main(), Persist the entity graph to SQLite, traverse it with NetworkX. WHY SQLite and…, Extract from the wiki and persist. Idempotent.

### Community 36 - "Retrieval Rrf"
Cohesion: 0.50
Nodes (4): FusedHit, Reciprocal Rank Fusion. WHY RRF over score normalisation: BM25 scores are…, Fuse two ranked lists. Either may be empty, which is how the ablation isolates…, reciprocal_rank_fusion()

### Community 37 - "External Types 37"
Cohesion: 0.40
Nodes (5): LLM_MODEL_SYNTHESIS env var, minimax/minimax-m3:free model, OpenRouter, LLMClient, VISION_LADDER (P1 provider config)

### Community 38 - "External Types 38"
Cohesion: 0.40
Nodes (5): Planted conflict question 1a_004, A4 Evidence Merger, ConflictAdapter, detect_conflicts (P1 conflict detector), SearchHit

### Community 39 - "External Types 39"
Cohesion: 0.40
Nodes (5): python -m src.graph.extract --apply-only, Rebuild count differences issue, Relations count discrepancy explained (379 wiki vs 742 total), tiktoken / estimate_tokens fallback, TOKENIZER_USED tracking

### Community 40 - "Core Llm"
Cohesion: 0.50
Nodes (3): NoProviderConfiguredError, RuntimeError, Raised when no provider has credentials. Names the fix, not just the fault.

### Community 41 - "External Types 41"
Cohesion: 0.67
Nodes (4): human-review.csv, tests.reasoning.acceptance runner, new_gold_docs field, tests.reasoning.review_report

### Community 42 - "External Types 42"
Cohesion: 0.50
Nodes (4): Question 1b_007, Ederon Fellgard, The Iron-Ring Cartel, The Leaden Accord

### Community 43 - "External Types 43"
Cohesion: 0.50
Nodes (4): Caption-binding figure fix (extends verbatim quote to indexed subject caption), Gold-text matching as diagnostic, not correctness, portrait-retest.json (caption-binding retest), post-fix-dev.json (8/20 dev run)

### Community 44 - "External Types 44"
Cohesion: 0.50
Nodes (4): Hosted CI run 34108890649, .github/workflows/reasoning.yml, test_chunk_provenance.py::test_every_chunk_lists_a_block_for_all_its_text (failing), test_chunker.py::test_a_single_long_block_is_split_at_sentence_boundaries (failing)

### Community 45 - "Synthesis Prompts"
Cohesion: 0.50
Nodes (3): messages(), Any, One prompt boundary for all reasoning calls; archive strings stay in evidence.

## Knowledge Gaps
- **42 isolated node(s):** `Bounded Orchestrator / State Machine`, `POST /v1/chat/jobs`, `GET /v1/traces/{id}`, `LLMClient`, `KNOWLEDGE_API_URL setting` (+37 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 362 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Settings` connect `Settings and Configuration` to `Indexing Embed`, `Core Llm`, `Graph Store`, `OCR Extraction`, `Block and Chunk Contracts`, `Tracing and Usage`, `Retry and Circuit Breaking`, `Image Description`, `Retrieval Seam and Expansion`, `Indexing Qdrant`, `API Main`, `Indexing Bm25`, `Indexing Embed`, `Core Llm`?**
  _High betweenness centrality (0.159) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `Indexing Embed` to `Indexing Embed`, `Conflict Adaptation`, `Agent Wiring`, `Graph Store`, `OCR Extraction`, `Block and Chunk Contracts`, `Tracing and Usage`, `Retry and Circuit Breaking`, `Vocabulary Loading`, `Image Description`, `Settings and Configuration`, `Indexing Qdrant`, `API Main`, `API Routes`, `Indexing Bm25`, `API Routes`?**
  _High betweenness centrality (0.156) - this node is a cross-community bridge._
- **Why does `Frozen` connect `Frozen API Schemas` to `Answer Composition (A5)`, `Conflict Adaptation`, `Query Analysis (A1)`, `Block and Chunk Contracts`, `Tracing and Usage`, `Retrieval Seam and Expansion`, `API Routes`, `Agents Analyst`, `Indexing Bm25`?**
  _High betweenness centrality (0.140) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `Settings` (e.g. with `_vector_count()` and `BedrockProvider`) actually correct?**
  _`Settings` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `Orchestrator` (e.g. with `Analysis` and `QueryAnalyst`) actually correct?**
  _`Orchestrator` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `get_settings()` (e.g. with `_load_entities()` and `metrics()`) actually correct?**
  _`get_settings()` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `SearchHit` (e.g. with `AnswerComposer` and `_portrait_quotes()`) actually correct?**
  _`SearchHit` has 16 INFERRED edges - model-reasoned connections that need verification._