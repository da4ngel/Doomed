# Architecture

Every number here is measured on the real archive, not estimated.

---

## 1. The shape

```
                    data/corpus/  (READ-ONLY, 341 files)
                              │
   ┌──────────────────────────┴───────────────────────────┐
   │                    INGESTION                          │
   │  pair format twins ─► adapters ─► scan route ─► OCR   │
   │  tier assign ─► chunk (tables atomic, figures alone)  │
   └──────────────────────────┬───────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   ┌────▼─────┐        ┌──────▼──────┐       ┌──────▼──────┐
   │  IMAGES  │        │   CHUNKS    │       │    GRAPH    │
   │ 70 VLM   │        │   2,474     │       │ 198 ent.    │
   │ described│───────►│  BM25 +     │       │ 379 rel.    │
   │          │        │  Qdrant     │       │ SQLite      │
   └──────────┘        └──────┬──────┘       └──────┬──────┘
                              │                     │
                    ┌─────────▼─────────────────────▼────────┐
                    │  hybrid → RRF → rerank → filter        │
                    └─────────────────┬──────────────────────┘
                                      │
                   ══════════ POST /v1/search ══════════   ◄── THE SEAM (frozen)
                                      │
                    ┌─────────────────▼──────────────────────┐
                    │  A1 Analyst → A2 Retrieval → A3 Critic │
                    │        ↑______________________|        │
                    │  → A4 Merger → A5 Composer → A6 Verify │
                    └─────────────────┬──────────────────────┘
                                      │
                              POST /v1/chat → answer packet
```

**The seam is `POST /v1/search`.** Everything above produces evidence; everything below
consumes it. It is frozen, tested by 56 Postman assertions, and it is what lets two
builders work in parallel without merging against each other.

---

## 2. Ingestion — corpus to chunks

### Format pairing (`src/ingestion/pairing.py`)

**254 files → 236 logical documents.** The four novels and three codexes ship as both
`.pdf` and `.docx` with *identical* extracted text.

Indexing both is not merely wasteful. A4 breaks equal-tier conflicts by counting
independent corroborating sources, so one source appearing twice would look corroborated
— turning an honest "unresolved, here are both sides" into a confident wrong answer with
two real citations.

PDF is canonical because it alone carries page numbers and bboxes. **Except when it is a
scan:** for 2 of the 17 scanned files the canonical PDF has no text layer while its twin
holds the content (similarity between them measured **0.000**), so scans sort last.

### Adapters (`src/ingestion/adapters/`)

Each returns `list[Block]` against the frozen schema. Format knowledge stops here.

| Adapter | Structure source |
|---|---|
| `pdf_adapter` | font-size clustering **plus bold weight** |
| `docx_adapter` | heading styles; tables read from table objects |
| `markdown_adapter` | `#` headings; the Infobox stays one atomic block |
| `text_adapter` | blank lines |

Two findings shaped this:

- **PDFs carry no table of contents** (0 outline entries). Font size separates structure
  — but the Annals has only *two* sizes above body text, and 19 of its 82 headings are
  bold at body size. Adding weight took PDF/DOCX outline agreement from **72.2% → 93.8%**;
  the residual is titles on pages with no text layer.
- **All 46 ephemera `.txt` files are markdown**, carrying 86 headings and 68 table rows.
  The adapter is chosen by content, not extension.

### OCR (`src/ingestion/ocr.py`)

Routing is a filename check — `*.scan.pdf`, all 17 — with a <50 chars/page density
heuristic as fallback. **39 blocks recovered at median 0.952 confidence**, and documents
producing zero blocks fell from 15 to **0**. No page fell below the 0.75 threshold, so
the VLM fallback for scans is unused.

Tesseract degrades rather than raises when absent: a judge without the binary loses a
field, never a run.

### Chunking (`src/ingestion/chunker.py`)

**2,474 chunks, median 391 tokens.** Three rules outrank the size target:

1. **Never split a table** — half a table is unanswerable.
2. **Never span a section boundary** — so `section_path` names a real place.
3. **Figures stand alone** — padding a VLM description with prose dilutes it.

Size is derived from the embedding model's **512-token context**, not a round number
(ADR-008). A 600-token target left 173 chunks (8.8%) indexed but only partly embedded —
present in the store, unreachable by dense retrieval, with no error to notice.

---

## 3. Images — where over half the marks are

**70 unique images** from 85 files; `images/` and `codex/images/` hold the same 15 plates
byte-identically, so the registry deduplicates by content hash.

Each image gets a **structured** VLM description — `values[]` binding each label to its
value — not prose. That is the whole mechanism:

```json
[{"label": "Old Imperial minimum",  "value": "800"},
 {"label": "Border-march standard", "value": "2,400"},
 {"label": "Great Keep standard",   "value": "6,000"},
 {"label": "Emberdeep",             "value": "1,114"}]
```

`plate_01` is a planted trap: 1,114 is Emberdeep's figure, drawn **shorter** than the
6,000 reference bar, so "largest number" and "longest bar" both fail. Measured on this
machine, **Tesseract 5.4 reads every label at 95% confidence and none of the numbers.**

**Gold recovery: 11/11. Cost: $0.00** on `minimax/minimax-m3:free`.

Captions and entity links are fully deterministic — every wiki image is referenced by
exactly one article whose alt text is the entity name, and every plate filename names a
subject matching a wiki article. So all 70 link into the graph at zero cost.

---

## 4. Graph — the 1B spine

**198 entities, 379 relations, zero LLM calls.** Built from wiki Infobox rows and
`[[wikilinks]]`, so every edge cites the row it came from: *"how do you know this edge is
real?"* has a line-number answer.

The infobox vocabulary is a long tail of ~100 labels, not 13 — `member_of` alone appears
as seven field names — so the extractor is a surface-form map, and unmapped fields are
**counted rather than dropped** (currently 100% coverage).

Entity ids are **article-insensitive and nothing else**. "The Iron-Ring Cartel" and
"Iron-Ring Cartel" were separate entities, splitting the graph: the Purge of Blackport was
won by one while the members belonged to the other. A named prefix, not a similarity
threshold — broader merging is what turns Greyfell into Ironfell.

`distinct_paths` collapses routes by entity chain: the same chain attested by an infobox
row *and* a prose sentence is one route corroborated twice, not two routes.

---

## 5. Retrieval

Dense (Qdrant, BGE-small 384d) + sparse (BM25) → **RRF k=60** → cross-encoder rerank →
payload filters. Every stage independently toggleable, so the ablation is nine
configurations of one function rather than nine implementations.

RRF fuses on **rank, not score**: BM25 is unbounded, cosine is [-1,1], and any
normalisation would itself need defending. Fifteen lines, derivable on a whiteboard.

Sparse matters more here than usual. The corpus is invented proper nouns with planted
near-miss decoys — `greyfell_citadel` (3,695, image-only) beside `ironfell_citadel`
(1,096, in text) — where dense similarity actively pulls the wrong pair together.

**Warm latency 1,106 ms with rerank, 76 ms without** — so rerank costs ~1,030 ms, the
first hard number for its ablation row.

---

## 6. Conflict layer (A4)

Load-bearing for **1A and 1C**, not a bonus. `1a_004`: the tier-1 plate says the
Thrice-Bound Edge costs **94**; the tier-2 wiki asserts "no attunement cost" six times
*and outranks the plate on dense similarity*.

Extraction is pattern-based, not an LLM call — a reported conflict must be verifiable by
opening two documents, and a hallucinated disagreement manufactures doubt about facts
nobody disputes. Attribution requires **type agreement** (only a Location has a founding
year) and **nearest preceding mention** (the codex gazetteer is a flat run of records, so
one chunk holds several entries).

**7 conflicts across the corpus**, including both 1C answers:

| Attribute | Winner | Loser | Resolution |
|---|---|---|---|
| Gloamreach founding year | 246 AS (t1 codex) | 286 AS (t4 contract) | higher_tier |
| Gauntlet forging year | 391 AS (t1 codex) | 360 AS (t5 sermon) | higher_tier |

**Equal tiers refuse to resolve.** Refusing is the feature.

---

## 7. Storage

| Store | Holds | Backed by |
|---|---|---|
| Documents / Blocks / Chunks | extracted content | JSONL |
| Dense vectors | 2,474 × 384d + filterable payload | Qdrant (Docker) |
| Sparse | BM25 over the same chunks | `bm25s` |
| Graph | 198 entities, 379 sourced relations | SQLite + NetworkX |
| Traces | every agent step, live | SQLite |
| Cache | `sha256(model+prompt+params)` | SQLite |

Qdrant runs as a Docker service *or* embedded from one class, chosen by `QDRANT_URL`. The
service is primary because embedded Qdrant is single-process — during development an index
build held the lock and the API could not open the store, which on demo day is a deadlock.

---

## 8. What this architecture refuses to do

- **Fuzzy-match an invented proper noun.** `resolved: false` beats a wrong number with a
  real citation.
- **Resolve a conflict between equal tiers.** Both sides are surfaced.
- **Compose from model knowledge.** The world is invented; anything the model "knows" is
  hallucinated by definition.
- **Treat retrieved text as instruction.** Evidence always enters prompts inside a
  delimited block.
- **Report a stage succeeded without checking its count.** Three separate indexing bugs
  printed a success line while being wrong — 2,441 chunks indexed as 256 vectors among
  them — so the eval harness now refuses to score an empty index.
