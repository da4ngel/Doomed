# Live integration issues for P1 review

> **All three answered below, 7 September.** Two were real and are fixed; one did
> not reproduce and is fixed anyway. See **P1 response** under each.

Observed on 7 September with 236 documents, 2,487 chunks, 70 described images,
198 entities, and 379 relations. No P1-owned source was edited for these issues.

## Embedded Qdrant readiness

1. Start `src.api.main:app` with embedded Qdrant.
2. Call `/v1/ready`; the index can initially report ready.
3. Execute a real hybrid search (which opens the retriever's vector store).
4. Call `/v1/ready` again: status becomes degraded despite successful search.

`src/api/main.py` creates a new `QdrantStore(settings)` to count vectors instead of
using the retriever's open store. The second embedded client cannot acquire the same
storage lock. The acceptance runner correctly blocks on this readiness response.
Suggested P1 fix: count through the existing retriever/store and close all owned
resources consistently. Test readiness both before and after an actual search.

## One image reported as two conflicting sources

Run `pytest tests/unit/test_conflicts.py::test_every_conflict_names_two_real_sources`
after ingesting the full image records. It fails for Mournwatch garrison strength:
8,254 versus 6,254, both tier 1, both attributed to
`images/plate_11_location_mournwatch.png`.

The image's VLM description and OCR text disagree. This needs source-image inspection
and an explicit treatment of extraction disagreement. It must not be presented as two
independent archive sources, nor silently resolved by discarding one reading. The
original image and generated `data/index/images.jsonl` are available locally.

## Rebuild count differences

The local graph build returns 198 entities rather than the handbook's 203; relations
remain 379. The final chunk build returns 2,487 including 70 figure chunks rather than
2,444. Earlier sandboxed text-only runs used tokenizer fallback and are not comparable.
Confirm counts against the same revision, tokenizer availability, and image model output.

---

# P1 response

## 1. Embedded Qdrant readiness - REAL, FIXED

Confirmed by reading `src/api/main.py` and reproduced in embedded mode:

```
BEFORE search   old  2444    new  2444
AFTER  search   old   -1     new  2444
```

`/v1/ready` now counts through `get_retriever().vectors`, the store the retriever
already owns. The standalone store survives only as a fallback for a process where
the retriever never loaded, and it closes what it opens.

It never appeared here because this machine runs Qdrant in **server** mode, where a
second client is just another connection. Good catch - it needed embedded to surface.

`tests/integration/test_api_health.py::test_readiness_survives_a_real_search` asserts
the count is INVARIANT across a real search rather than asserting a fixed number, so
it holds in whichever backend the suite runs against. Against the unfixed code it
fails with "vector count moved across a search: 2444 -> -1".

Formal acceptance was not relaxed to tolerate a degraded readiness state.

## 2. One image as two sources - REPRODUCED IN FULL, FIXED

**Correction to an earlier draft of this file, which said this machine had no
Tesseract.** It does: 5.4.0 at `C:\Program Files\Tesseract-OCR`, and `ocr.py` already
knows to look there. The binary was installed after the index was built, so every
image record carried a stale `ocr_available: false`. Re-running the image step - all
70 descriptions served from cache, $0.00 - populated OCR and reproduced your bug
exactly.

**You were right, and the image settles it.** Direct inspection of
`plate_11_location_mournwatch.png` shows **8,254** on a 0-9,904 gauge, `souls under
arms`. The vision model read it correctly. Tesseract returned:

```
Mournwatch RECORDED GARRISON STRENGTH 6,254 souls under arms
```

**at 0.899 mean confidence.** That is the part worth keeping: the misread is
*confident*. A confidence threshold would not have caught it, so the fix cannot be a
quality gate - it has to be structural.

With OCR present, `test_every_conflict_names_two_real_sources` now fails here on the
real index, exactly as you reported: same png on both sides, tier 1 against tier 1.

`detect_conflicts` now treats a cluster whose two sides resolve to the same single
doc_id, with every assertion from an `img:` chunk, as one picture read twice. It is
recorded in the new `MergeReport.extraction_disagreements` - preserved for audit, as
you asked, never rendered as an archive disagreement and never silently discarded.
Against the rebuilt index the layer now returns **6 genuine conflicts and 1 extraction
disagreement**, so the guard suppressed the false one without touching the real ones.

Scope, measured across all 70 images: **Mournwatch is the only plate in the corpus
where OCR and the VLM disagree on a value.** One case - but a tier-1 figure, and the
1C answers are built out of this layer.

Two further things the OCR run confirmed, both previously asserted:

| claim | measured |
|---|---|
| `atmo_*` yields no OCR text | 54 of 55 yield nothing |
| `plate_*` yields clean text | 15/15, 58-147 chars |
| "Tesseract missed 1,114 entirely" on the Emberdeep trap | it missed **every number on that chart** - 141 chars of labels, no digits at all, at 0.95 confidence, while the VLM recovered all four values including 1,114 |

## 3. Count differences - TWO OF THREE EXPLAINED, ONE HYPOTHESIS DISPROVEN

| | yours | here | verdict |
|---|---|---|---|
| entities | 198 | 198 | **agree.** The handbook's 203 was stale; main corrected it before you read it |
| relations | 379 | 742 | **explained.** 379 is the deterministic wiki graph. The other 363 are LLM-extracted and merged by `python -m src.graph.extract --apply-only`, which landed after this branch forked |
| chunks | 2,487 | 2,474 | **13 still unexplained** |

**A hypothesis this file previously called leading is now disproven.** The idea was
that appended OCR text pushed image chunks past the split threshold, producing both
your extra chunks and the same-image conflict. It does not: rebuilt with OCR fully
populated, the chunker still returns **2,474 chunks, 70 figure chunks** - unchanged.
Image chunks top out around 1,195 characters and OCR adds at most 147, nowhere near
the 450-token boundary. The two symptoms have different causes.

That leaves the image descriptions themselves as the remaining candidate: a different
VLM run produces different `searchable_text`, and figure chunks are the only ones a
VLM run can move. Ours came from `minimax/minimax-m3:free`, all 70 cached.

The tokenizer is no longer a candidate *here* but was worth your raising, and it is
now traceable rather than silent: `estimate_tokens` fell back to a 4-chars-per-token
estimate without saying so, and `tiktoken.get_encoding` DOWNLOADS its BPE table on
first use, so an offline machine chunks differently from identical inputs. It now
warns once per process and `TOKENIZER_USED` records which counter ran.

Reproducible here: **236 documents, 3,134 blocks, 2,474 chunks, 70 described images
(15 figure_plate + 55 wiki_image, 16 carrying OCR), 198 entities, 379 wiki relations /
742 after extraction**, tiktoken cl100k_base, Tesseract 5.4.0, Qdrant server mode.