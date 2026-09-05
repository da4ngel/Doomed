# Corpus Findings — Addendum

Discovered 5 Sep 2026 while hand-authoring the 1A gold labels from the images.
Extends `docs/corpus-findings.md`; same precedence (below `CLAUDE.md`, above the master plan).

---

## Finding 7 — `1a_004` is a planted **contradiction**, not just a chart question

This is the most consequential thing found today.

`1a_004` asks: *"According to the figure plate detailing weapon binding, how many shards
of will are required to attune The Thrice-Bound Edge?"*

| Source | Tier | Says |
|---|---|---|
| `images/plate_04_artifact_the_thrice_bound_edge.png` | 1 | **94** (measured in vitae-grains) |
| `wiki/the_thrice_bound_edge.md` | 2 | **"no attunement cost"** — stated **six times** |

The wiki article does not merely omit the value. It asserts the absence at length:
`| Attunement cost | None recorded |` in the infobox, plus *"The surviving record does
not provide an attunement cost… This absence is part of the artifact's documented
profile."*

Three consequences:

1. **The conflict layer is load-bearing for 1A, not only 1C.** Finding 4 established
   that both 1C questions are contradiction questions. This shows a 1A question is one
   too. A4's tier resolution (tier 1 plate beats tier 2 fan wiki) is now on the critical
   path for the largest block of the dev set. It cannot be deferred to D4.
2. **The wiki article is an active retrieval decoy.** A dense retriever given
   "attunement cost of the Thrice-Bound Edge" will rank that article first — it is
   topically perfect and repeats the key phrase. It yields a confident, fluent,
   well-cited *wrong* answer. Nothing but the image carries the truth.
3. **"Shards of will" appears nowhere in the corpus.** Verified across every `.md`,
   `.txt` and all 1,248 PDF pages: zero occurrences. The plate says *vitae-grains*. So
   question vocabulary deliberately diverges from corpus vocabulary, and A1 must not
   "normalise" the phrase into something it thinks it recognises.

## Finding 8 — the confusable-artifact pair is a retrieval test

| Plate | Subject value | Reference bars |
|---|---|---|
| `plate_04` The Thrice-Bound **Edge** | **94** | 20 / 55 / 85 |
| `plate_07` The Thrice-Bound **Lantern** | **55** | 20 / 55 / 85 |
| `plate_13` The Cinder-Wrought Aegis | **34** | 20 / 55 / 85 |

Two distinct traps stack here:

- **Name collision.** "The Thrice-Bound Edge" and "The Thrice-Bound Lantern" differ by
  one token. Retrieve the wrong plate and the answer is confidently wrong. This is
  precisely where BM25 on rare invented proper nouns beats dense similarity, and it is
  a concrete ablation argument rather than a theoretical one.
- **Value collision.** The Lantern's own answer (**55**) is *identical* to the "Adept
  tolerance" reference bar on its own plate. A model that extracts numbers without
  binding them to labels cannot tell which 55 is the subject's — and would be right by
  luck rather than by reading.

## Finding 9 — the chart trap generalises beyond bar charts

`plate_08` (Weeping Lurker threat rating) is a **gauge**, not a bar chart. The answer is
**3**, but the axis endpoints "0" and "10" are also rendered as text, and the caption
reads *"of 10, per the Vanguard scale"*. Flat OCR yields `3`, `0`, `10` with no
structure; "pick the largest" gives 10.

The Emberdeep bar chart has a matching property worth stating in the report: the 1,114
bar is drawn **shorter** than the 6,000 reference bar. So the trap defeats *both* naive
strategies — "read the biggest number" and "read the longest bar".

**Therefore `chart_reading` must cover three figure grammars**, not one: grouped bar
chart with reference bars, single-value plate, and gauge.

## Finding 10 — only 70 of the 85 images are unique

`images/` and `codex/images/` hold the **same 15 plates, byte-for-byte identical**
(verified by sha256). Unique image count is therefore **70**, in 15 duplicate groups.

- VLM description work drops ~18%. Keying the cache on content hash makes this
  automatic — the second copy is a cache hit, not a second call.
- The asset registry **must** dedupe by content hash, or a figure question returns the
  same plate twice and `asset_precision` is quietly wrong.
- Both paths land in tier 1 under the directory-first rule, so there is no tier
  conflict to resolve — but a citation should name one canonical path.

## Finding 11 — the location garrison figures exist in no document at all

Confirms Finding 1 by direct check rather than inference. `wiki/emberdeep.md` and
`wiki/greyfell_citadel.md` contain **no** garrison number; the Greyfell article
describes the citadel as abandoned and explicitly declines to describe "its former
garrison". The values 1,114 and 3,695 exist **only** as pixels.

Any pipeline without figure understanding scores zero on these, no matter how good its
text retrieval is.

---

## What this changes

| Change | From | To |
|---|---|---|
| A4 conflict layer | D3, for 1C | **D2 — also on the 1A path** (Finding 7) |
| Asset registry | one row per file | **dedupe by content hash** (Finding 10) |
| `chart_reading` suite | 4 bar charts | **3 figure grammars**: bar+reference, single value, gauge (Finding 9) |
| Ablation argument for BM25 | generic "rare proper nouns" | **the Edge/Lantern pair, measurable** (Finding 8) |
| A1 normalisation | correct against entity vocabulary | **also: never rewrite an unknown unit** (Finding 7) |

---

## Finding 12 — the wiki infobox vocabulary is a long tail, not 13 clean fields

Finding 3 showed a tidy example (`Member of`, `Commands`, `Wields`, `Mentor of`) and
concluded the graph parses deterministically. That conclusion holds, but the
implementation is not a lookup on 13 field names. Across the 95 articles there are
**over 100 distinct infobox field labels**, and the target predicates are spread thin:

| Predicate | Surface forms actually present |
|---|---|
| `member_of` | Member of (14), Membership (10), Affiliation (12), Members (3), Member (1), Known members (1), Allegiance (1) |
| `commands` | Command (11), Commands (1), Castellan (1) |
| `wields` | Wielded relic (3), Wields (2), Weapon (2), Relic (2), Wielded weapon (1), Weapon or Relic (1) |
| `ruled_by` | Ruled by (17), Ruler (6), Ruling power (1) |
| `housed_at` | Housed in (11), Place of housing (1) |
| `mentor_of` | Mentor of (3), Mentor (3), Mentorship (3) |

Some labels even carry the value inside the field name — `Serves at Emberdeep`,
`Serving at Crookvale`, `Personnel serving at Hollowreach`.

So the extractor needs a **surface-form → predicate map plus a field-name value
fallback**. Still deterministic, still zero LLM cost, still zero hallucination risk —
but a parser keyed on the 13 canonical names would silently capture a small fraction of
the graph and nobody would notice, because a sparse graph fails quietly.

Also: **89 of 95 articles have an Infobox section**, not all 95. The remaining 6 need
the prose/wikilink path alone.

## Finding 13 — plated locations and wiki-garrison locations are disjoint by design

The 8 locations with a garrison plate and the 17 wiki articles carrying a
`Garrison strength` infobox row are **completely non-overlapping** (verified: zero
intersection).

| Plated (image only) | Nearest wiki name with a garrison figure |
|---|---|
| Greyfell Citadel — 3,695 | Ironfell **Citadel** — 1,096 |
| Embercrag Fortress | Vharen**crag Fortress** — 9,478 |
| Hollowreach / Marrowwatch / Mournwatch | Gloam**reach** — 2,483 |
| Emberdeep — 1,114 | Crookvale — 1,004 · Embermarch — 4,063 |

This is the most dangerous trap in the corpus, and it is not a vision problem at all.
A system that fuzzy-matches an unfamiliar proper noun, or that settles for "a wiki
article about a similar-sounding place", returns a garrison number that is **fluent,
plausible, and carries a genuine citation to a real document**. It fails in exactly the
way a judge cannot catch by reading the answer alone.

Two direct consequences:

1. **Entity-aware normalisation (differentiator 6) is defensive, not cosmetic.** A1 must
   correct only against the entity vocabulary and must never map Emberdeep onto
   Embermarch. Every correction is shown and reversible.
2. **This is the strongest concrete argument for hybrid retrieval in the ablation.** BM25
   on exact rare proper nouns separates `greyfell` from `ironfell`; dense similarity
   actively pulls them together. Row 1 versus row 4 of the ablation table can be
   explained with this example rather than in the abstract.
