# Live integration issues for P1 review

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
