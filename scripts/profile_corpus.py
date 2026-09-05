#!/usr/bin/env python3
"""
profile_corpus.py — Ashen Era Archive corpus profiler.

The D0 gate deliverable. Produces docs/corpus-profile.md and docs/corpus-profile.json.

The number that matters most is the SCANNED PAGE RATIO. It decides how much of D1
goes to the OCR path versus the born-digital path, and it is the one input the whole
ingestion design depends on. Everything else here is supporting context.

Usage
-----
    python scripts/profile_corpus.py --corpus data/corpus --out docs
    python scripts/profile_corpus.py --corpus data/corpus --out docs --tables
    python scripts/profile_corpus.py --corpus data/corpus --out docs --sample 50

Options
-------
    --tables   run table detection on PDFs. Accurate but slow on ~1,300 pages.
               Leave it off for the first pass; turn it on overnight.
    --sample N profile only the first N files. Use for a fast sanity check.

Dependencies
------------
    uv add pymupdf python-docx pillow
    python-docx and pillow are optional; the script degrades gracefully and reports
    what it could not inspect rather than failing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------------
# Tunables. These are the heuristics the ingestion pipeline will inherit — keep them
# here and import them from src/ingestion/ rather than duplicating the numbers.
# --------------------------------------------------------------------------------

SCANNED_CHAR_THRESHOLD = 50      # chars of extractable text below which a page is a scan
SPARSE_CHAR_THRESHOLD = 200      # 50-200 chars: ambiguous (figure plate? title page?)
FULLPAGE_IMAGE_COVERAGE = 0.60   # image area / page area that confirms a scan
CHARS_PER_PAGE_ESTIMATE = 1800   # for estimating page counts of DOCX / MD / TXT

TEXT_EXTS = {".md", ".markdown", ".txt", ".rst"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}

# Authority tier guesses from path and filename. Order matters: the most distinctive
# markers are checked first. This is a GUESS that a human must review — the output
# report says so explicitly.
TIER_PATTERNS: list[tuple[int, str, str]] = [
    (5, "folkloric",   r"ballad|tavern|rumou?r|hearsay|folk|legend|song|tale|verse|ditty"),
    (1, "codex",       r"codex|plate|datasheet|data[\s_-]?book|reference|appendix|table[\s_-]?\d|figure[\s_-]?plate"),
    (2, "wiki",        r"wiki|encyclop|article|entry|lexicon|gazetteer"),
    (4, "record",      r"letter|ledger|transcript|trial|dispatch|decree|order|manifest|receipt|deposition|writ|invoice|inventory"),
    (3, "narrative",   r"novel|volume|vol[\s_.\-]?\d|chapter|book[\s_.\-]?\d|part[\s_.\-]?\d"),
]

TIER_LABELS = {
    1: "Tier 1 — official reference",
    2: "Tier 2 — encyclopaedic",
    3: "Tier 3 — primary narrative",
    4: "Tier 4 — primary record",
    5: "Tier 5 — unreliable / folkloric",
    0: "UNCLASSIFIED — needs a human rule",
}

CHAR_BINS = [0, 50, 200, 500, 1000, 2000, 4000, 10**9]
CHAR_BIN_LABELS = [
    "0-49 (scan)", "50-199 (sparse)", "200-499", "500-999",
    "1000-1999", "2000-3999", "4000+",
]


# --------------------------------------------------------------------------------
# Optional imports
# --------------------------------------------------------------------------------

def _try_import(name: str) -> Any:
    try:
        return __import__(name)
    except ImportError:
        return None


# PyMuPDF renamed its module: prefer `pymupdf`, fall back to the legacy `fitz`
# name so this runs on either version without emitting a deprecation warning.
fitz = _try_import("pymupdf") or _try_import("fitz")
_docx_mod = _try_import("docx")     # python-docx
_PIL = _try_import("PIL")
if _PIL is not None:
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        _PIL = None


# --------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------

@dataclass
class PageProfile:
    page: int
    chars: int
    images: int
    max_image_coverage: float = 0.0
    tables: int = 0
    classification: str = "digital"     # digital | scanned | sparse


@dataclass
class FileProfile:
    path: str
    ext: str
    size_bytes: int
    kind: str                            # pdf | docx | text | image | other
    pages: int = 0
    pages_estimated: bool = False
    total_chars: int = 0
    images: int = 0
    tables: int = 0
    headings: int = 0
    tier_guess: int = 0
    tier_reason: str = ""
    scanned_pages: int = 0
    sparse_pages: int = 0
    digital_pages: int = 0
    page_profiles: list[PageProfile] = field(default_factory=list)
    error: str | None = None


# --------------------------------------------------------------------------------
# Tier guessing
# --------------------------------------------------------------------------------

def guess_tier(path: Path, corpus_root: Path) -> tuple[int, str]:
    """Guess an authority tier from the path. A human must review the result."""
    try:
        rel = str(path.relative_to(corpus_root))
    except ValueError:
        rel = str(path)
    haystack = rel.lower().replace("\\", "/")
    for tier, label, pattern in TIER_PATTERNS:
        m = re.search(pattern, haystack)
        if m:
            return tier, f"matched '{m.group(0)}' ({label})"
    return 0, "no pattern matched"


# --------------------------------------------------------------------------------
# Per-format profilers
# --------------------------------------------------------------------------------

def profile_pdf(path: Path, want_tables: bool) -> FileProfile:
    prof = FileProfile(
        path=str(path), ext=path.suffix.lower(),
        size_bytes=path.stat().st_size, kind="pdf",
    )
    if fitz is None:
        prof.error = "PyMuPDF not installed (uv add pymupdf)"
        return prof

    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001
        prof.error = f"open failed: {type(exc).__name__}: {exc}"
        return prof

    try:
        prof.pages = doc.page_count
        for pno in range(doc.page_count):
            try:
                page = doc.load_page(pno)
                text = page.get_text("text") or ""
                chars = len(text.strip())

                page_area = max(float(page.rect.width) * float(page.rect.height), 1.0)
                images = page.get_images(full=True)
                max_cov = 0.0
                for img in images:
                    try:
                        for rect in page.get_image_rects(img[0]):
                            cov = (rect.width * rect.height) / page_area
                            max_cov = max(max_cov, float(cov))
                    except Exception:  # noqa: BLE001
                        pass

                ntables = 0
                if want_tables:
                    try:
                        found = page.find_tables()
                        ntables = len(found.tables)
                    except Exception:  # noqa: BLE001
                        ntables = 0

                if chars < SCANNED_CHAR_THRESHOLD:
                    cls = "scanned"
                elif chars < SPARSE_CHAR_THRESHOLD:
                    cls = "sparse"
                else:
                    cls = "digital"

                pp = PageProfile(
                    page=pno + 1, chars=chars, images=len(images),
                    max_image_coverage=round(max_cov, 3),
                    tables=ntables, classification=cls,
                )
                prof.page_profiles.append(pp)
                prof.total_chars += chars
                prof.images += len(images)
                prof.tables += ntables
                if cls == "scanned":
                    prof.scanned_pages += 1
                elif cls == "sparse":
                    prof.sparse_pages += 1
                else:
                    prof.digital_pages += 1
            except Exception as exc:  # noqa: BLE001
                prof.page_profiles.append(
                    PageProfile(page=pno + 1, chars=0, images=0, classification="scanned")
                )
                prof.scanned_pages += 1
                if prof.error is None:
                    prof.error = f"page {pno + 1}: {type(exc).__name__}: {exc}"
    finally:
        doc.close()

    return prof


def profile_docx(path: Path) -> FileProfile:
    prof = FileProfile(
        path=str(path), ext=path.suffix.lower(),
        size_bytes=path.stat().st_size, kind="docx",
    )

    # Embedded media is readable from the zip without python-docx.
    try:
        with zipfile.ZipFile(path) as zf:
            prof.images = sum(1 for n in zf.namelist() if n.startswith("word/media/"))
    except Exception as exc:  # noqa: BLE001
        prof.error = f"zip read failed: {type(exc).__name__}: {exc}"

    if _docx_mod is None:
        if prof.error is None:
            prof.error = "python-docx not installed (uv add python-docx)"
        return prof

    try:
        d = _docx_mod.Document(str(path))
        chars = 0
        headings = 0
        for p in d.paragraphs:
            chars += len(p.text)
            style = (p.style.name or "") if p.style is not None else ""
            if style.lower().startswith("heading"):
                headings += 1
        for t in d.tables:
            for row in t.rows:
                for cell in row.cells:
                    chars += len(cell.text)
        prof.total_chars = chars
        prof.headings = headings
        prof.tables = len(d.tables)
        prof.pages = max(1, round(chars / CHARS_PER_PAGE_ESTIMATE))
        prof.pages_estimated = True
        prof.digital_pages = prof.pages
    except Exception as exc:  # noqa: BLE001
        prof.error = f"docx parse failed: {type(exc).__name__}: {exc}"

    return prof


def profile_text(path: Path) -> FileProfile:
    prof = FileProfile(
        path=str(path), ext=path.suffix.lower(),
        size_bytes=path.stat().st_size, kind="text",
    )
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        prof.total_chars = len(raw)
        prof.headings = len(re.findall(r"^#{1,6}\s", raw, flags=re.MULTILINE))
        # Markdown pipe tables: a header row followed by a separator row.
        prof.tables = len(re.findall(r"^\|.*\|\s*\n\|[\s:\-|]+\|\s*$", raw, flags=re.MULTILINE))
        prof.images = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", raw))
        prof.pages = max(1, round(len(raw) / CHARS_PER_PAGE_ESTIMATE))
        prof.pages_estimated = True
        prof.digital_pages = prof.pages
    except Exception as exc:  # noqa: BLE001
        prof.error = f"read failed: {type(exc).__name__}: {exc}"
    return prof


def profile_image(path: Path) -> FileProfile:
    prof = FileProfile(
        path=str(path), ext=path.suffix.lower(),
        size_bytes=path.stat().st_size, kind="image",
        pages=1, images=1, scanned_pages=1,
    )
    if _PIL is not None:
        try:
            from PIL import Image
            with Image.open(path) as im:
                prof.tier_reason = f"{im.size[0]}x{im.size[1]} {im.mode}"
        except Exception as exc:  # noqa: BLE001
            prof.error = f"image open failed: {type(exc).__name__}: {exc}"
    return prof


# --------------------------------------------------------------------------------
# Walk and aggregate
# --------------------------------------------------------------------------------

def walk_corpus(root: Path, sample: int | None) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            files.append(Path(dirpath) / fn)
    files.sort()
    return files[:sample] if sample else files


def profile_file(path: Path, corpus_root: Path, want_tables: bool) -> FileProfile:
    ext = path.suffix.lower()
    if ext == ".pdf":
        prof = profile_pdf(path, want_tables)
    elif ext in {".docx", ".dotx"}:
        prof = profile_docx(path)
    elif ext in TEXT_EXTS:
        prof = profile_text(path)
    elif ext in IMAGE_EXTS:
        prof = profile_image(path)
    else:
        prof = FileProfile(
            path=str(path), ext=ext, size_bytes=path.stat().st_size, kind="other",
            error="unhandled extension — decide whether ingestion should skip it",
        )
    tier, reason = guess_tier(path, corpus_root)
    prof.tier_guess = tier
    if not prof.tier_reason:
        prof.tier_reason = reason
    return prof


def bin_index(n: int) -> int:
    for i in range(len(CHAR_BINS) - 1):
        if CHAR_BINS[i] <= n < CHAR_BINS[i + 1]:
            return i
    return len(CHAR_BIN_LABELS) - 1


def aggregate(profiles: list[FileProfile]) -> dict[str, Any]:
    by_ext = Counter(p.ext or "(none)" for p in profiles)
    by_kind = Counter(p.kind for p in profiles)
    by_tier = Counter(p.tier_guess for p in profiles)

    pages_by_kind: dict[str, int] = defaultdict(int)
    for p in profiles:
        pages_by_kind[p.kind] += p.pages

    hist = [0] * len(CHAR_BIN_LABELS)
    for p in profiles:
        for pp in p.page_profiles:
            hist[bin_index(pp.chars)] += 1

    total_pdf_pages = sum(p.pages for p in profiles if p.kind == "pdf")
    scanned = sum(p.scanned_pages for p in profiles if p.kind == "pdf")
    sparse = sum(p.sparse_pages for p in profiles if p.kind == "pdf")
    digital = sum(p.digital_pages for p in profiles if p.kind == "pdf")

    errors = [p for p in profiles if p.error]
    ocr_files = sorted(
        [p for p in profiles if p.kind == "pdf" and p.scanned_pages > 0],
        key=lambda p: p.scanned_pages, reverse=True,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(profiles),
        "total_pages": sum(p.pages for p in profiles),
        "total_chars": sum(p.total_chars for p in profiles),
        "total_images": sum(p.images for p in profiles),
        "total_tables": sum(p.tables for p in profiles),
        "by_ext": dict(by_ext.most_common()),
        "by_kind": dict(by_kind.most_common()),
        "by_tier": {TIER_LABELS[k]: v for k, v in sorted(by_tier.items())},
        "pages_by_kind": dict(pages_by_kind),
        "pdf_pages": {
            "total": total_pdf_pages,
            "scanned": scanned,
            "sparse": sparse,
            "digital": digital,
            "scanned_ratio": round(scanned / total_pdf_pages, 4) if total_pdf_pages else 0.0,
            "ocr_candidate_ratio": round((scanned + sparse) / total_pdf_pages, 4) if total_pdf_pages else 0.0,
        },
        "char_histogram": dict(zip(CHAR_BIN_LABELS, hist)),
        "error_count": len(errors),
        "errors": [{"path": p.path, "error": p.error} for p in errors[:50]],
        "ocr_heavy_files": [
            {"path": p.path, "scanned_pages": p.scanned_pages, "total_pages": p.pages}
            for p in ocr_files[:25]
        ],
    }


# --------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------

def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def ingestion_verdict(agg: dict[str, Any]) -> str:
    pdf = agg["pdf_pages"]
    ratio = pdf["ocr_candidate_ratio"]
    scanned = pdf["scanned"] + pdf["sparse"]
    if pdf["total"] == 0:
        return ("No PDF pages found. Either the corpus path is wrong or the archive is "
                "text-first. Confirm the path before drawing any conclusion.")
    if ratio < 0.05:
        band = ("**Low.** The OCR path is an edge case, not a pillar. Build born-digital "
                "extraction properly and give OCR a 2-hour timebox on D1. Reallocate the "
                "saved time to the entity graph, which is the 1B spine.")
    elif ratio < 0.20:
        band = ("**Moderate.** Budget roughly half of D1 morning for the OCR path. Tesseract "
                "first, VLM fallback only below the confidence threshold. Report the OCR "
                "failure rate in `limitations.md` — it is honest and it scores.")
    elif ratio < 0.50:
        band = ("**High.** OCR quality is now a primary risk to answer quality, not a side "
                "path. Give it most of D1 morning, cache aggressively, and measure OCR "
                "confidence per page as a first-class metric. Consider making OCR quality "
                "one of your ablation rows.")
    else:
        band = ("**Dominant.** The archive is effectively a scan corpus. Reorder D1 to put "
                "OCR first and treat born-digital extraction as the special case. A VLM "
                "pass over scanned pages may beat Tesseract outright — measure both on 20 "
                "pages before committing, and record the comparison as an ADR.")
    return (f"{scanned} of {pdf['total']} PDF pages ({ratio:.1%}) need the OCR path.\n\n{band}")


def render_markdown(agg: dict[str, Any], profiles: list[FileProfile], corpus: Path) -> str:
    pdf = agg["pdf_pages"]
    L: list[str] = []
    a = L.append

    a("# Corpus Profile — Ashen Era Archive")
    a("")
    a(f"Generated `{agg['generated_at']}` from `{corpus}` by `scripts/profile_corpus.py`.")
    a("")
    a("This is the D0 gate deliverable. The scanned-page ratio below is the single number")
    a("that determines how D1 is spent.")
    a("")

    a("## Headline")
    a("")
    a(md_table(["Measure", "Value"], [
        ["Files", agg["file_count"]],
        ["Pages (actual + estimated)", agg["total_pages"]],
        ["Characters of extractable text", f"{agg['total_chars']:,}"],
        ["Embedded images", agg["total_images"]],
        ["Tables detected", agg["total_tables"]],
        ["PDF pages", pdf["total"]],
        ["→ born-digital", f"{pdf['digital']} ({1 - pdf['ocr_candidate_ratio']:.1%})"],
        ["→ sparse / ambiguous", pdf["sparse"]],
        ["→ scanned", f"{pdf['scanned']} ({pdf['scanned_ratio']:.1%})"],
        ["Files that failed inspection", agg["error_count"]],
    ]))
    a("")

    a("## Ingestion verdict")
    a("")
    a(ingestion_verdict(agg))
    a("")

    a("## Embedding budget")
    a("")
    est_tokens = int(agg["total_chars"] / 4 * 1.15)   # ~4 chars/token, +15% chunk overlap
    a(f"Approximately **{est_tokens:,} tokens** to embed, including chunk overlap.")
    a("")
    if est_tokens > 0:
        reindexes = 200_000_000 // max(est_tokens, 1)
        a(f"Against Voyage's 200M free allowance that is roughly **{reindexes:,} full re-indexes**.")
        a("Re-indexing is effectively free — never let index cost drive a design decision.")
    a("")

    a("## By file type")
    a("")
    a(md_table(["Extension", "Files"], [[k, v] for k, v in agg["by_ext"].items()]))
    a("")
    a(md_table(["Handler", "Files", "Pages"],
               [[k, v, agg["pages_by_kind"].get(k, 0)] for k, v in agg["by_kind"].items()]))
    a("")

    a("## Authority tier — GUESS, needs human review")
    a("")
    a("Assigned by filename and path pattern. Review this table and correct the rules in")
    a("`src/ingestion/tiers.py` before D1 ends. Anything UNCLASSIFIED needs a rule or an")
    a("explicit default, because tier drives conflict resolution in agent A4.")
    a("")
    a(md_table(["Tier", "Files"], [[k, v] for k, v in agg["by_tier"].items()]))
    a("")

    a("## Text density per PDF page")
    a("")
    a("The first two bins are the OCR workload. Everything from 200 chars up is born-digital.")
    a("")
    a(md_table(["Chars on page", "Pages"], [[k, v] for k, v in agg["char_histogram"].items()]))
    a("")

    if agg["ocr_heavy_files"]:
        a("## Files needing the most OCR")
        a("")
        a("Use these as the parser test fixtures. If ingestion works on these, it works.")
        a("")
        a(md_table(["File", "Scanned pages", "Total pages"],
                   [[Path(f["path"]).name, f["scanned_pages"], f["total_pages"]]
                    for f in agg["ocr_heavy_files"]]))
        a("")

    if agg["errors"]:
        a("## Failed inspection — dead-letter preview")
        a("")
        a("These files broke the profiler. They will break ingestion too unless handled.")
        a("This is exactly why ingestion needs a dead-letter list rather than a hard failure.")
        a("")
        a(md_table(["File", "Error"],
                   [[Path(e["path"]).name, e["error"]] for e in agg["errors"]]))
        a("")

    a("## What to do with this")
    a("")
    a("1. Act on the ingestion verdict above — it sets D1's shape.")
    a("2. Review and correct the tier rules. Tier drives A4 conflict resolution; a wrong")
    a("   tier table produces confidently wrong conflict outcomes.")
    a("3. Take the OCR-heavy files as parser fixtures.")
    a("4. Put the headline numbers on page 2 of the submission report. \"We profiled the")
    a("   corpus before designing ingestion\" is *Problem understanding & insight*, and")
    a("   these are the numbers that prove it.")
    a("")
    return "\n".join(L)


# --------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Profile the Ashen Era Archive corpus.")
    ap.add_argument("--corpus", required=True, type=Path, help="path to the corpus root")
    ap.add_argument("--out", default=Path("docs"), type=Path, help="output directory")
    ap.add_argument("--tables", action="store_true", help="run PDF table detection (slow)")
    ap.add_argument("--sample", type=int, default=None, help="profile only the first N files")
    args = ap.parse_args()

    corpus: Path = args.corpus
    if not corpus.exists():
        print(f"error: corpus path does not exist: {corpus}", file=sys.stderr)
        return 2

    if fitz is None:
        print("warning: PyMuPDF missing — PDFs will not be profiled. `uv add pymupdf`",
              file=sys.stderr)
    if _docx_mod is None:
        print("warning: python-docx missing — DOCX text will not be counted. `uv add python-docx`",
              file=sys.stderr)

    files = walk_corpus(corpus, args.sample)
    if not files:
        print(f"error: no files found under {corpus}", file=sys.stderr)
        return 2

    print(f"profiling {len(files)} files from {corpus} ...", file=sys.stderr)
    profiles: list[FileProfile] = []
    for i, f in enumerate(files, 1):
        profiles.append(profile_file(f, corpus, args.tables))
        if i % 25 == 0 or i == len(files):
            print(f"  {i}/{len(files)}", file=sys.stderr)

    agg = aggregate(profiles)

    args.out.mkdir(parents=True, exist_ok=True)
    md_path = args.out / "corpus-profile.md"
    json_path = args.out / "corpus-profile.json"

    md_path.write_text(render_markdown(agg, profiles, corpus), encoding="utf-8")
    json_path.write_text(
        json.dumps({"summary": agg, "files": [asdict(p) for p in profiles]},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    pdf = agg["pdf_pages"]
    print("", file=sys.stderr)
    print(f"wrote {md_path}", file=sys.stderr)
    print(f"wrote {json_path}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"  files            {agg['file_count']}", file=sys.stderr)
    print(f"  pages            {agg['total_pages']}", file=sys.stderr)
    print(f"  PDF pages        {pdf['total']}", file=sys.stderr)
    print(f"  needing OCR      {pdf['scanned'] + pdf['sparse']} ({pdf['ocr_candidate_ratio']:.1%})",
          file=sys.stderr)
    print(f"  failed to read   {agg['error_count']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
