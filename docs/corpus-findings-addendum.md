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
