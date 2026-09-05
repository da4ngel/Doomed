"""Describe every corpus image with a vision model, deterministically captioned.

WHY this is P0 rather than a nice extra: 11 of the 20 dev questions are sub-track 1A and
their answers exist *only* inside these images. `1a_009` asks for Greyfell Citadel's
garrison strength; 3,695 appears in no document in the archive. Roughly 55 of the images
return zero OCR characters, so there is no text-extraction path to them at all.

WHY the description is structured JSON and not prose: `plate_01` is a planted trap - a bar
chart whose reference bars read 800 / 2,400 / 6,000 with the real Emberdeep figure of
1,114 drawn *shorter* than the 6,000 bar. A prose description contains all four numbers
with nothing distinguishing the answer from the references, so the composer picks wrong.
Demanding `values[]` as label/value pairs is what makes the answer recoverable. This is
measured, not assumed: see ADR-002.

WHY captions and entity links are free here: every wiki image is referenced by exactly one
article whose alt text is the entity name, and every plate filename parses as
`plate_<NN>_<category>_<subject>` where the subject matches a wiki article. So each image
links into the entity graph with zero LLM cost and zero guessing - no proximity heuristic
anywhere in this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.config import Settings, get_settings
from src.core.llm import LLMClient, NoProviderConfiguredError
from src.graph.wiki_extract import entity_id
from src.ingestion.ocr import ocr_image, tesseract_available
from src.ingestion.tiers import assign_tier, source_type

log = logging.getLogger(__name__)

#: The exact prompt validated in the spike. `values[]` binding is the whole point - see
#: the module docstring. The spike imports this so what we tested is what ships.
INSTRUCTION = """You are reading a figure plate from an archive. Return ONLY JSON:

{
  "kind": "bar_chart | gauge | portrait | heraldry | landscape | relic | table | diagram | other",
  "subject": "what this plate is about",
  "values": [{"label": "exact label as printed", "value": "exact value as printed"}],
  "objects_depicted": ["objects actually visible in the image"],
  "text_visible": "every piece of text you can read, verbatim",
  "description": "two sentences describing the plate"
}

Rules:
- If this is a chart or gauge, `values` MUST bind every bar, row or reading to its own
  label. Reference lines, baselines, comparison standards and axis endpoints are separate
  entries from the subject.
- Report only what is printed. Do not infer, round, or pick the largest number.
- If a value belongs to the plate's named subject, label it with that subject's name.
- For a portrait or relic, list what is actually held, worn or engraved in
  `objects_depicted`. Be specific: "rolled scroll", not "an object".
"""

#: (provider, model), cheapest first. Free tier passed all three spike cases; the paid
#: rungs exist so one 429 during the final index run cannot cost us the figure answers.
VISION_LADDER: list[tuple[str, str]] = [
    ("openrouter", "minimax/minimax-m3:free"),
    ("openrouter", "google/gemma-4-31b-it:free"),
    ("openrouter", "thinkingmachines/inkling:free"),
    ("openai", "gpt-4o-mini"),
]

_PLATE = re.compile(r"^plate_(\d+)_([a-z]+)_(.+)$")
_IMAGE_REF = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


@dataclass
class ImageRecord:
    asset_id: str
    paths: list[str]
    canonical_path: str
    authority_tier: int
    source_type: str
    caption: str
    entity_link: str | None
    owner_document: str | None = None
    kind: str = ""
    subject: str = ""
    values: list[dict[str, Any]] = field(default_factory=list)
    objects_depicted: list[str] = field(default_factory=list)
    description: str = ""
    text_visible: str = ""
    ocr_text: str = ""
    ocr_char_count: int = 0
    ocr_confidence: float | None = None
    ocr_available: bool = True
    searchable_text: str = ""
    model: str = ""
    provider: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cached: bool = False

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_wiki_image_index(corpus_root: Path) -> dict[str, tuple[str, str]]:
    """Map `wiki/images/<file>` -> (owning article path, alt text).

    Verified 1:1 across the corpus: 55 images, 55 references, none shared, none orphaned.
    The alt text is the entity name, which is why no proximity heuristic is needed.
    """
    index: dict[str, tuple[str, str]] = {}
    wiki = corpus_root / "wiki"
    for article in sorted(wiki.glob("*.md")):
        text = article.read_text(encoding="utf-8", errors="replace")
        for alt, src in _IMAGE_REF.findall(text):
            key = f"wiki/{src.lstrip('./')}"
            index.setdefault(key, (f"wiki/{article.name}", alt.strip()))
    return index


def caption_and_entity(
    rel_path: str, wiki_index: dict[str, tuple[str, str]]
) -> tuple[str, str | None, str | None]:
    """Return (caption, entity_link, owning_document) for one image, deterministically."""
    name = Path(rel_path).stem

    plate = _PLATE.match(name)
    if plate:
        index, category, subject = plate.groups()
        pretty = subject.replace("_", " ").title()
        return (
            f"Plate {index} - {pretty} ({category})",
            entity_id(subject.replace("_", " ")),
            None,
        )

    if rel_path in wiki_index:
        article, alt = wiki_index[rel_path]
        return (alt, entity_id(alt) if alt else None, article)

    return (name.replace("_", " "), None, None)


def render_searchable_text(record: ImageRecord) -> str:
    """Compose the text the chunker will embed.

    `values[]` is rendered as explicit `label: value` lines rather than flattened into
    prose. Flattening would re-introduce the exact ambiguity the vision model was chosen
    to remove - the index would contain 1,114 and 6,000 with nothing to say which belongs
    to Emberdeep.
    """
    parts = [record.caption]
    if record.subject:
        parts.append(f"Subject: {record.subject}")
    if record.description:
        parts.append(record.description)
    if record.values:
        parts.append("Recorded values:")
        parts.extend(f"  {v.get('label', '?')}: {v.get('value', '?')}" for v in record.values)
    if record.objects_depicted:
        parts.append("Depicted: " + ", ".join(str(o) for o in record.objects_depicted))
    if record.text_visible:
        parts.append(f"Text in image: {record.text_visible}")
    if record.ocr_text:
        parts.append(f"OCR: {record.ocr_text}")
    return "\n".join(p for p in parts if p)


def discover_images(corpus_root: Path) -> dict[str, list[str]]:
    """Group every corpus PNG by content hash. 85 files collapse to 70 unique images."""
    groups: dict[str, list[str]] = defaultdict(list)
    for path in sorted(corpus_root.rglob("*.png")):
        groups[sha256_file(path)].append(str(path.relative_to(corpus_root)).replace("\\", "/"))
    return dict(groups)


def _canonical(paths: list[str]) -> str:
    """Prefer the standalone `images/` copy as the citable path, for stable citations."""
    for path in paths:
        if path.startswith("images/"):
            return path
    return paths[0]


def describe_one(
    client: LLMClient,
    corpus_root: Path,
    digest: str,
    paths: list[str],
    wiki_index: dict[str, tuple[str, str]],
    ladder: list[tuple[str, str]],
) -> ImageRecord:
    """Describe one unique image, walking the ladder until a model answers."""
    canonical = _canonical(paths)
    tier, _ = assign_tier(canonical)
    caption, entity, owner = caption_and_entity(canonical, wiki_index)

    record = ImageRecord(
        asset_id=f"img_{digest[:16]}",
        paths=paths,
        canonical_path=canonical,
        authority_tier=tier,
        source_type=source_type(canonical),
        caption=caption,
        entity_link=entity,
        owner_document=owner,
    )

    ocr = ocr_image(corpus_root / canonical)
    record.ocr_text = ocr.text
    record.ocr_char_count = ocr.char_count
    record.ocr_confidence = ocr.mean_confidence
    record.ocr_available = ocr.available

    last_error: Exception | None = None
    for provider, model in ladder:
        try:
            response = client.describe_image(
                corpus_root / canonical,
                INSTRUCTION,
                model=model,
                provider=provider,
                json_mode=True,
            )
            payload = response.json_payload()
        except Exception as exc:  # noqa: BLE001 - try the next rung
            last_error = exc
            log.warning("%s failed on %s (%s:%s)", type(exc).__name__, canonical, provider, model)
            continue

        if not isinstance(payload, dict):
            last_error = ValueError("model returned non-object JSON")
            continue

        record.kind = str(payload.get("kind", ""))
        record.subject = str(payload.get("subject", ""))
        values = payload.get("values") or []
        record.values = [v for v in values if isinstance(v, dict)]
        objects = payload.get("objects_depicted") or []
        record.objects_depicted = [str(o) for o in objects]
        record.description = str(payload.get("description", ""))
        record.text_visible = str(payload.get("text_visible", ""))
        record.model = model
        record.provider = response.provider
        record.tokens_in = response.tokens_in
        record.tokens_out = response.tokens_out
        record.cost_usd = response.cost_usd
        record.cached = response.cached
        record.searchable_text = render_searchable_text(record)
        return record

    raise RuntimeError(f"every vision model failed on {canonical}: {last_error}")


def run(
    settings: Settings | None = None,
    limit: int | None = None,
    ladder: list[tuple[str, str]] | None = None,
    workers: int = 3,
) -> tuple[list[ImageRecord], list[dict[str, str]]]:
    """Describe every unique image. Returns (records, dead_letter)."""
    settings = settings or get_settings()
    corpus_root = settings.corpus_root
    client = LLMClient(settings)

    available = set(client.available_providers())
    if not available:
        raise NoProviderConfiguredError
    chosen = [(p, m) for p, m in (ladder or VISION_LADDER) if p in available]
    if not chosen:
        raise NoProviderConfiguredError

    wiki_index = build_wiki_image_index(corpus_root)
    groups = discover_images(corpus_root)
    items = sorted(groups.items())[: limit or None]

    log.info(
        "describing %d unique images from %d files",
        len(items),
        sum(len(p) for _, p in groups.items()),
    )

    records: list[ImageRecord] = []
    dead_letter: list[dict[str, str]] = []

    def work(item: tuple[str, list[str]]) -> ImageRecord | dict[str, str]:
        digest, paths = item
        try:
            return describe_one(client, corpus_root, digest, paths, wiki_index, chosen)
        except Exception as exc:  # noqa: BLE001 - dead-letter, never halt the run
            return {"paths": ", ".join(paths), "error": f"{type(exc).__name__}: {exc}"}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, outcome in enumerate(pool.map(work, items), start=1):
            if isinstance(outcome, ImageRecord):
                records.append(outcome)
            else:
                dead_letter.append(outcome)
            if done % 10 == 0 or done == len(items):
                print(f"  {done}/{len(items)} described", flush=True)

    return records, dead_letter


def write_outputs(
    records: list[ImageRecord], dead_letter: list[dict[str, str]], settings: Settings
) -> Path:
    """Write atomically - a half-written index is worse than a missing one."""
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    target = settings.index_dir / "images.jsonl"
    tmp = target.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "\n".join(r.to_json() for r in sorted(records, key=lambda r: r.canonical_path)) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)

    dead_path = settings.index_dir / "images.deadletter.jsonl"
    if dead_letter:
        dead_path.write_text("\n".join(json.dumps(d) for d in dead_letter) + "\n", encoding="utf-8")
    elif dead_path.exists():
        dead_path.unlink()
    return target


def print_stats(records: list[ImageRecord], dead_letter: list[dict[str, str]]) -> None:
    from collections import Counter

    print(f"\ndescribed      : {len(records)}")
    print(f"dead-letter    : {len(dead_letter)}")
    print(f"total cost     : ${sum(r.cost_usd for r in records):.4f}")
    print(
        f"tokens in/out  : {sum(r.tokens_in for r in records)}/{sum(r.tokens_out for r in records)}"
    )
    print(f"cached         : {sum(1 for r in records if r.cached)}")
    print(f"with values[]  : {sum(1 for r in records if r.values)}")
    print(f"entity-linked  : {sum(1 for r in records if r.entity_link)}")
    zero_ocr = sum(1 for r in records if r.ocr_available and r.ocr_char_count == 0)
    if any(r.ocr_available for r in records):
        print(f"zero-OCR images: {zero_ocr}  (the case for a vision model, measured)")
    else:
        print("OCR            : tesseract not installed - ocr fields are empty")
    print("\nby model:")
    for model, count in Counter(r.model for r in records).most_common():
        print(f"  {model:44s} {count}")
    for entry in dead_letter:
        print(f"  DEAD: {entry['paths']} - {entry['error'][:120]}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="describe only the first N unique images")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--stats", action="store_true", help="summarise an existing run")
    args = parser.parse_args()

    settings = get_settings()

    if args.stats:
        path = settings.index_dir / "images.jsonl"
        if not path.exists():
            print("no images.jsonl yet - run without --stats first")
            return 1
        records = [
            ImageRecord(**json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        dead = settings.index_dir / "images.deadletter.jsonl"
        dead_letter = (
            [json.loads(line) for line in dead.read_text(encoding="utf-8").splitlines() if line]
            if dead.exists()
            else []
        )
        print_stats(records, dead_letter)
        return 0

    if not tesseract_available():
        print("note: tesseract not found - OCR fields will be empty, VLM path unaffected")

    try:
        records, dead_letter = run(settings, limit=args.limit, workers=args.workers)
    except NoProviderConfiguredError as exc:
        print(f"\n{exc}\n")
        return 2

    target = write_outputs(records, dead_letter, settings)
    print_stats(records, dead_letter)
    print(f"\nwrote {target}")
    return 0 if not dead_letter else 1


if __name__ == "__main__":
    sys.exit(main())
