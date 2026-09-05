---
description: Re-ingest a small corpus subset and smoke-test retrieval end to end
argument-hint: [number of documents, default 30]
allowed-tools: Bash, Read
---

Fast ingestion feedback loop on **$ARGUMENTS** documents (default 30).

1. `make ingest SUBSET=$ARGUMENTS` against a scratch index — never the full index.
2. Report the ingestion summary:
   - documents processed / skipped by checksum / dead-lettered
   - blocks by type: text, table, figure, caption, heading
   - pages routed to OCR, and the OCR confidence distribution
   - figures with a linked caption vs orphaned figures
   - chunks produced, token distribution, and **any chunk containing a partial table**
     (this must be zero — a split table is unanswerable)
3. Print the dead-letter list with the exception for each entry.
4. Run three smoke retrievals against the subset — one text question, one figure
   question, one multi-entity question — and print the top 3 hits with scores,
   `source_type` and `authority_tier` for each.
5. Flag anything that looks wrong: empty blocks, zero-area bboxes, duplicate
   `block_id`s, figures with no description, chunks over the token cap, or a tier
   distribution that does not match `docs/corpus-profile.md`.

Keep this under 90 seconds. If it gets slower than that, it stops being used.
