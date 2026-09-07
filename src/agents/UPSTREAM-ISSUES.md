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

## 2. One image as two sources - DID NOT REPRODUCE, FIXED REGARDLESS

`test_every_conflict_names_two_real_sources` passes here, 22/22 in that file. The
reason is environmental, not a difference of opinion: **this machine has no Tesseract**,
so all 70 images carry `ocr_available: false` and `ocr_char_count: 0`. There is no
6,254 anywhere in the index. Your build has OCR; mine does not.

You are right on the substance. Direct inspection confirms **8,254**, gauge maximum
9,904, and 6,254 is an extraction error rather than an independent archive source.

Mechanism, which also explains issue 3: the assertion extractor keeps one value per
(entity, attribute) per chunk, so the two readings cannot collide inside a single
chunk. They must have been in **two chunks of the same image** - meaning appended OCR
text pushed those image chunks past the split threshold.

`detect_conflicts` now treats a cluster whose two sides resolve to the same single
doc_id, with every assertion from an `img:` chunk, as one picture read twice. It is
recorded in the new `MergeReport.extraction_disagreements` - preserved for audit, as
you asked, never rendered as an archive disagreement and never silently discarded.
The guard is narrow: a control test proves two genuinely different documents still
conflict normally.

The regression tests build the case directly from the real indexed plate text with
the digit misread, so they do not depend on whichever VLM or OCR run is in the index.
Removing the guard reproduces your failure verbatim:

```
Mournwatch garrison strength names images/plate_11_location_mournwatch.png
on both sides
```

## 3. Count differences - TWO OF THREE EXPLAINED

| | yours | here | verdict |
|---|---|---|---|
| entities | 198 | 198 | **agree.** The handbook's 203 was stale; main corrected it before you read it |
| relations | 379 | 742 | **explained.** 379 is the deterministic wiki graph. The other 363 are LLM-extracted and merged by `python -m src.graph.extract --apply-only`, which landed after this branch forked |
| chunks | 2,487 | 2,474 | **13 unexplained**, two candidate causes below |

The chunker has not changed since the branch point and the corpus is read-only, so
the code is identical on both sides. That leaves two candidates:

- **Tesseract.** OCR text appended to image chunks pushes the largest past the split
  threshold. The same mechanism issue 2 requires. This is the leading explanation.
- **The tokenizer.** You were right to name it. `estimate_tokens` fell back to a
  4-chars-per-token estimate *silently*, and `tiktoken.get_encoding` DOWNLOADS its BPE
  table on first use, so an offline machine chunks differently from identical inputs.

The silence was the real defect. The fallback now warns once per process in terms that
say what it costs, and `TOKENIZER_USED` records which counter actually ran, so a chunk
count can be traced to its denominator instead of argued about. A test asserts this
build is genuinely on tiktoken rather than hoping so.

Reproducible here: **236 documents, 2,474 chunks, 70 described images (15 figure_plate
+ 55 wiki_image), 198 entities, 379 wiki relations / 742 after extraction**, tiktoken
cl100k_base, no Tesseract, Qdrant server mode.
