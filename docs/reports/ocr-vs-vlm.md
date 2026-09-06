# Tesseract vs. vision model, measured

Generated 2026-09-06T11:40:41+00:00 by `scripts/ocr_vs_vlm.py`.
Tesseract 5.4.0.20240606 · vision model `minimax/minimax-m3:free` · 70 unique images.

This is our own measurement on this machine, not a claim inherited from the
corpus profile. It is the evidence behind ADR-002.

## Characters extracted, by image class

| Class | n | median chars | mean chars | images with **zero** chars |
|---|---|---|---|---|
| atmo_* (portraits, heraldry, creatures) | 55 | 0 | 0 | **54 / 55** |
| plate_* (figure plates) | 15 | 135 | 111 | **0 / 15** |

## Gold answer recoverable per channel

| Question | Gold answer | Tesseract | Vision model |
|---|---|---|---|
| `1a_001` | 1,114 | **no** | yes |
| `1a_009` | 3,695 | yes | yes |
| `1a_008` | 3 | **no** | yes |
| `1a_004` | 94 | **no** | yes |
| `1a_007` | 55 | yes | yes |
| `1a_013` | 34 | yes | yes |
| `1a_v06` | a rolled scroll | **no** | yes |
| `1a_v07` | a chalice | **no** | yes |
| `1a_v12` | two crossed keys | **no** | yes |
| `1a_v11` | a weeping eye | **no** | yes |
| `1a_v21` | a serpent | **no** | yes |

**Tesseract recovers 3 of 11. The vision model recovers 11 of 11.**

## The trap plate, side by side

`plate_01_location_emberdeep.png` asks for Emberdeep's garrison strength.

Tesseract, flat text:

```
Emberdeep - Recorded Garrison Strength Old Imperial minimum Border-march standard Great Keep standard Emberdeep Measured in souls under arms.
```

Vision model, label-bound values:

```json
[
  {
    "label": "Old Imperial minimum",
    "value": "800"
  },
  {
    "label": "Border-march standard",
    "value": "2,400"
  },
  {
    "label": "Great Keep standard",
    "value": "6,000"
  },
  {
    "label": "Emberdeep",
    "value": "1,114"
  }
]
```

The reference bars are the danger. Flat text carries 800, 2,400 and 6,000
with nothing marking which number belongs to Emberdeep, so a fluent model
answers 6,000 and cites a real figure plate while doing it.

## What this does and does not say

OCR is not broken. It is being asked the wrong question. On rendered plate text
it reads cleanly; on painted portraits and heraldry there is no glyph to read at
all, and on a chart it cannot express which label owns which number. That is a
representational limit, not a quality one - which is why the fix is a different
extraction channel rather than a better OCR configuration.

Tesseract is kept in the pipeline: it still routes the 41 scanned PDF pages, and
its per-word confidence feeds the OCR confidence distribution reported in
`limitations.md`.
