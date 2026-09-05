# Corpus Profile — Ashen Era Archive

Generated `2026-09-04T12:41:43+00:00` from `/home/claude/corpus/Ashen_Era_Archive` by `scripts/profile_corpus.py`.

This is the D0 gate deliverable. The scanned-page ratio below is the single number
that determines how D1 is spent.

## Headline

| Measure | Value |
|---|---|
| Files | 341 |
| Pages (actual + estimated) | 2937 |
| Characters of extractable text | 5,022,441 |
| Embedded images | 205 |
| Tables detected | 225 |
| PDF pages | 1248 |
| → born-digital | 1179 (94.5%) |
| → sparse / ambiguous | 28 |
| → scanned | 41 (3.3%) |
| Files that failed inspection | 1 |

## Ingestion verdict

69 of 1248 PDF pages (5.5%) need the OCR path.

**Moderate.** Budget roughly half of D1 morning for the OCR path. Tesseract first, VLM fallback only below the confidence threshold. Report the OCR failure rate in `limitations.md` — it is honest and it scores.

## Embedding budget

Approximately **1,443,951 tokens** to embed, including chunk overlap.

Against Voyage's 200M free allowance that is roughly **138 full re-indexes**.
Re-indexing is effectively free — never let index cost drive a design decision.

## By file type

| Extension | Files |
|---|---|
| .md | 95 |
| .png | 85 |
| .pdf | 63 |
| .docx | 50 |
| .txt | 47 |
| .json | 1 |

| Handler | Files | Pages |
|---|---|---|
| text | 142 | 459 |
| image | 85 | 85 |
| pdf | 63 | 1248 |
| docx | 50 | 1145 |
| other | 1 | 0 |

## Authority tier — GUESS, needs human review

Assigned by filename and path pattern. Review this table and correct the rules in
`src/ingestion/tiers.py` before D1 ends. Anything UNCLASSIFIED needs a rule or an
explicit default, because tier drives conflict resolution in agent A4.

| Tier | Files |
|---|---|
| UNCLASSIFIED — needs a human rule | 87 |
| Tier 1 — official reference | 36 |
| Tier 2 — encyclopaedic | 150 |
| Tier 3 — primary narrative | 8 |
| Tier 4 — primary record | 41 |
| Tier 5 — unreliable / folkloric | 19 |

## Text density per PDF page

The first two bins are the OCR workload. Everything from 200 chars up is born-digital.

| Chars on page | Pages |
|---|---|
| 0-49 (scan) | 41 |
| 50-199 (sparse) | 28 |
| 200-499 | 19 |
| 500-999 | 50 |
| 1000-1999 | 758 |
| 2000-3999 | 352 |
| 4000+ | 0 |

## Files needing the most OCR

Use these as the parser test fixtures. If ingestion works on these, it works.

| File | Scanned pages | Total pages |
|---|---|---|
| interrogation_record_concerning_crookgate_keep.scan.pdf | 3 | 3 |
| interrogation_record_concerning_greyfell_citadel.scan.pdf | 3 | 3 |
| interrogation_record_concerning_hesper_wrenfield.scan.pdf | 3 | 3 |
| the_ashen_chronicles_volume_ii_the_long_reprisal.pdf | 2 | 248 |
| the_annals_of_the_ashen_era.pdf | 2 | 73 |
| ballad_concerning_crookgate_keep.scan.pdf | 2 | 2 |
| contract_concerning_halvard_sablewood.scan.pdf | 2 | 2 |
| contract_concerning_marsh_revenant.scan.pdf | 2 | 2 |
| contract_concerning_the_cinder_wrought_aegis.scan.pdf | 2 | 2 |
| field_report_concerning_cerys_sablewood_the_ashen.scan.pdf | 2 | 2 |
| interrogation_record_concerning_ashreach.scan.pdf | 2 | 2 |
| letter_concerning_the_accord_of_mournthrone.scan.pdf | 2 | 2 |
| petition_concerning_halvard_cindervale.scan.pdf | 2 | 2 |
| petition_concerning_morwenna_morvain.scan.pdf | 2 | 2 |
| sermon_concerning_fenthrone.scan.pdf | 2 | 2 |
| sermon_concerning_marsh_revenant.scan.pdf | 2 | 2 |
| sermon_concerning_salt_blind_leviathan.scan.pdf | 2 | 2 |
| codex_vaeloria_i_gazetteer_of_the_sundered_realms.pdf | 1 | 46 |
| codex_vaeloria_ii_armory_of_relics_and_bestiary.pdf | 1 | 42 |
| ballad_concerning_the_sceptre_of_final_winter.scan.pdf | 1 | 1 |
| muster_roll_concerning_hollowvale.scan.pdf | 1 | 1 |

## Failed inspection — dead-letter preview

These files broke the profiler. They will break ingestion too unless handled.
This is exactly why ingestion needs a dead-letter list rather than a hard failure.

| File | Error |
|---|---|
| sample_questions.json | unhandled extension — decide whether ingestion should skip it |

## What to do with this

1. Act on the ingestion verdict above — it sets D1's shape.
2. Review and correct the tier rules. Tier drives A4 conflict resolution; a wrong
   tier table produces confidently wrong conflict outcomes.
3. Take the OCR-heavy files as parser fixtures.
4. Put the headline numbers on page 2 of the submission report. "We profiled the
   corpus before designing ingestion" is *Problem understanding & insight*, and
   these are the numbers that prove it.
