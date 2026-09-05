# Corpus Findings — and what they change

Profiled from `Ashen_Era_Archive.zip`, 4 Sep 2026. Full report in `corpus-profile.md`,
raw data in `corpus-profile.json`. Commit both to `docs/`.

---

## Headline

| Measure | Value |
|---|---|
| Files | 341 (340 documents + `sample_questions.json`) |
| PDF pages (actual) | **1,248** |
| DOCX/MD/TXT pages (estimated) | ~1,689 |
| Extractable text | 5,022,441 chars ≈ **1.44M tokens to embed** |
| PNG images | **85** |
| Tables detected | 225 |
| Born-digital PDF pages | 1,179 (94.5%) |
| Scanned PDF pages | 41 (3.3%) |
| Sparse/ambiguous pages | 28 |

The brief's "415 documents, ~1,277 pages" maps to the 1,248 actual PDF pages; the real
file count is 340. Embedding the whole corpus costs about 0.7% of the Voyage free
allowance — roughly **138 full re-indexes**. Index cost is a non-issue; never let it
drive a design decision.

| Directory | Contents |
|---|---|
| `chronicles/` | 4 PDF + 4 DOCX — the novels. `volume_ii` alone is 248 pages |
| `codex/` | 3 PDF + 3 DOCX + 15 PNG plates |
| `ephemera/` | 56 PDF + 46 TXT + 43 DOCX — 12 document types |
| `wiki/` | 95 MD + 55 PNG |
| `images/` | 15 standalone plates |

---

## Finding 1 — 1A is the majority of the dev set, and the answers live inside images

`sample_questions.json` track distribution: **11 × 1A, 7 × 1B, 2 × 1C.** If the hidden
judging set mirrors this, **sub-track 1A is over half your score.**

Worse for the naive approach: the 1A questions are not "show me a relevant figure
beside the text." The fact **exists only in the image**. Verified: `1a_009` asks for
Greyfell Citadel's garrison strength; the answer `3,695` appears nowhere in any
document — only in `images/plate_09_location_greyfell_citadel.png`.

The 85 PNGs split into two classes with completely different handling:

| Class | Count | OCR yield | Questions |
|---|---|---|---|
| `plate_*` — figure plates | ~30 | 71–153 chars, clean | garrison strength, attunement cost, threat rating, casualties |
| `atmo_*` — portraits, heraldry, creatures, battles, landscapes | ~55 | **0 chars** | what object is held, what emblem is on the banner, what motif is engraved |

Measured with Tesseract across both sets. Every `atmo_*` image returned literally zero
characters. `1a_v06` ("what object is Ignatz Ashgrove holding?" — a rolled scroll) and
`1a_v12` ("central emblem on House Morvain's banner") are unanswerable without a
vision model. **There is no OCR-only path to those marks.**

### The planted trap

`1a_001` asks for Emberdeep's recorded garrison strength.
`images/plate_01_location_emberdeep.png` is a **bar chart with four numbers**: 800
(Old Imperial minimum), 2,400 (Border-march standard), 6,000 (Great Keep standard),
and **1,114 (Emberdeep)** — the answer.

Tesseract returned the reference values but **rendered the actual answer as `Ee`**,
missing it entirely. A pipeline that OCRs the plate and hands flat text to an LLM will
answer 6,000 or 800. This is deliberate: the designers built a chart where naive text
extraction produces a confident wrong answer.

**Requirement: figure *understanding*, not figure text extraction.** A VLM must produce
a structured description that binds each value to its label.

### What this changes

1. **VLM figure description moves from cut-line #3 to P0.** Cutting it forfeits the
   largest block of questions in the set. Delete it from the ladder entirely.
2. **The image pipeline is a D1 morning task**, not a byproduct of PDF parsing. 85 PNGs
   is a small, bounded, high-value job — describe every one, cache the results.
3. **Index three fields per image**: VLM structured description + OCR text + the
   markdown alt-text/caption. Embed the concatenation.
4. **New eval sub-suite: `chart_reading`.** Take the four bar-chart plates and assert
   the answer is the labelled value, not the largest. This is the single test most
   likely to separate you from teams that OCR and hope.
5. **Revised cut-line ladder:** 1. debug page · 2. evidence-graph UI viz ·
   3. graph path-finding · 4. ablation configs 2, 3, 6 · 5. streaming/SSE.

---

## Finding 2 — scan detection is free

All 17 scanned files are named `*.scan.pdf`. The heuristic still ships as a fallback
(and its measured agreement with the filename convention is a nice line in the report),
but routing is a filename check.

Only 41 pages need OCR at all, concentrated in 3-page interrogation records. **The OCR
path is a 2-hour job, not a half-day.** Reallocate the saved time to the image pipeline
in Finding 1, where the marks actually are.

---

## Finding 3 — the wiki hands you the entity graph

Wiki articles are structured markdown with `[[wikilinks]]` and an Infobox table:

```
| Field | Value |
| Role | Reliquary Keeper |
| Born | 315 AS |
| Member of | The Iron-Ring Cartel |
| Commands | Fenspire since 336 AS |
| Wields | The Silent Psalter since 341 AS |
| Mentor of | Thessaly Coldwater |
```

95 articles × structured infobox rows + inline `[[links]]` = a **high-precision graph
skeleton parsed deterministically, with zero LLM cost and zero hallucination risk.**

This inverts the D3 plan. Build the skeleton from infoboxes and wikilinks first, then
run LLM extraction only over `chronicles/` and `ephemera/`, where relations are prose.
That is most of a day saved on the longest pole in the project — and a deterministic
graph is far easier to defend to a judge than an LLM-extracted one.

Concrete relation schema, read off the actual dev questions and infobox fields:

```
member_of · commands · wields · bore_since · mentor_of · born_in
ruled_by · located_in · lair_of · won · fought_in · allied_with · secret
```

The 1B questions are 2–3 hop chains over exactly these:
- `1b_006` "which individual was a member of the faction that won the War of Drowned
  Light" → `war --won_by--> faction --has_member--> person`
- `1b_013` "whose dominion encompasses the lair of the Gravemaw Wyrm" →
  `creature --lair_in--> location --ruled_by--> house`
- `1b_003` "to which redoubt must one journey to examine the relic borne by Cerys
  Sablewood since 356 AS" → `person --bore_since--> relic --housed_at--> location`

Wiki images are embedded with relative paths and alt text
(`![Aldous Wrenfield](images/atmo_portrait_...png)`), so **image↔entity association is
free in the wiki** — no proximity heuristic needed there.

---

## Finding 4 — 1C questions are contradiction questions

Both 1C dev questions are phrased around disputed facts:

- `1c_000`: "State the **precise** year… that marks the **true** founding of Gloamreach."
- `1c_003`: "In which year was the Gauntlet of Sorrowfell **actually** forged?"

Gloamreach is mentioned across **11 files**, including text that names the uncertainty
around its foundation directly, alongside a wiki article asserting a specific year.
"True", "actually", "precise" are the tell: multiple sources give different years, and
the task is to resolve them.

**The A4 conflict/authority layer is therefore not a differentiator bolted onto the
side — it is the 1C answer path.** Iterative search finds the competing claims;
tier-based resolution picks the answer and shows the working. Move `conflicts[]` and
the tier table from "nice extra" to a load-bearing D3 dependency.

The corpus README confirms the design intent for `ephemera/`: in-world authors are not
always reliable.

---

## Finding 5 — tier assignment should be directory-first

The filename-pattern guess left **87 files unclassified**. The directory structure maps
to tiers almost perfectly, so make the directory the primary rule and the filename a
refinement. Replace the rules in `src/ingestion/tiers.py` with this:

```python
def assign_tier(rel_path: str) -> tuple[int, str]:
    p = rel_path.lower().replace("\\", "/")
    name = p.rsplit("/", 1)[-1]

    if p.startswith("codex/") or p.startswith("images/") or "/plate_" in p or name.startswith("plate_"):
        return 1, "codex / official figure plate"
    if p.startswith("wiki/"):
        return 2, "fan-wiki article"
    if p.startswith("chronicles/"):
        return 3, "narrative novel"
    if p.startswith("ephemera/"):
        if name.startswith(("ballad", "sermon")):
            return 5, "folkloric / homiletic — unreliable narrator"
        return 4, "in-world primary record"
    return 4, "unknown provenance — default to primary record, flag for review"
```

Resulting distribution across the 340 documents: **tier 1** ≈ 36 (codex + plates),
**tier 2** ≈ 150 (wiki + its images), **tier 3** = 8 (novels), **tier 4** ≈ 113
(records), **tier 5** = 32 (19 ballads + 13 sermons).

One judgment call to make explicitly and record as an ADR: the wiki is a *fan* wiki, so
tier 2 above the novels is arguable. The novels are primary canon; the wiki is
secondary commentary on it. Consider tier 2 = novels, tier 3 = wiki. Whichever you
choose, the reasoning belongs in the report — it is exactly the kind of judgment the
rubric rewards.

---

## Finding 6 — there are no gold answers in the dev set

`sample_questions.json` contains only `qid`, `track`, `question`. No answers, no
supporting documents, no assets.

**Every gold label must be hand-authored from the corpus.** M3's job is now confirmed
as mandatory and on the critical path — without it there is no ablation table, no
recall@10, no coverage@10, and no evaluation section in the report. Start it today.

Fastest route: the `plate_*` images make 1A gold labels trivial to author (open the
image, read the number). Do those 11 first — they are quick wins that unblock the
`chart_reading` sub-suite immediately.

---

## Revised priorities

| Change | From | To |
|---|---|---|
| VLM figure description | cut-line #3 | **P0, D1 morning** |
| OCR path | half of D1 morning | 2-hour job, 41 pages |
| Entity graph | LLM extraction over 1,277 pages | **deterministic from infoboxes + wikilinks first**, LLM only for chronicles + ephemera |
| Conflict layer (A4) | D4 differentiator | **D3, on the 1C critical path** |
| Tier rules | filename patterns | **directory-first** |
| New eval suite | — | `chart_reading` — the labelled value, not the largest |

The one-line version: **the marks are in the images, the graph is nearly free, and 1C
is a conflict problem.** Everything else in the master plan holds.
