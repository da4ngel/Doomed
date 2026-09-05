"""Blocks → Chunks. Structure-aware, with three rules that outrank the size target.

WHY the rules beat the sizes: a 600-token target is a tuning parameter and will be swept
(300/600/1000) as a reported experiment. The rules below are not tunable, because
breaking any of them produces chunks that cannot answer a question no matter how good
retrieval is:

1. **Never split a table.** Half a table is unanswerable - the rows are separated from
   the header that names them. The codex infoboxes are the densest facts in the corpus
   (`| Garrison strength | 2598 |`), and splitting one strands every row in it.
2. **Never merge across a section boundary.** A chunk must belong to exactly one section,
   so `Citation.section_path` names a real place a judge can open.
3. **Figures are standalone chunks.** An image already carries a VLM description whose
   `values[]` bind labels to numbers; padding it with unrelated prose dilutes the
   embedding of the one thing that makes 1A answerable.

Overlap exists so a fact spanning a boundary survives in at least one chunk whole. It is
applied within a section only - overlapping across a section boundary would reintroduce
rule 2 through the back door.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from src.api.schemas import Block, Chunk
from src.core.config import Settings, get_settings
from src.ingestion.adapters.base import estimate_tokens

#: Target chunk size. Swept in the ablation; the rules above are not.
TARGET_TOKENS = 600

#: Fraction of the target carried into the next chunk.
OVERLAP_RATIO = 0.15

#: A chunk below this is merged forward rather than indexed as a fragment.
MIN_TOKENS = 40


@dataclass
class ChunkStats:
    chunks: int = 0
    table_chunks: int = 0
    figure_chunks: int = 0
    oversized_tables: int = 0
    documents: int = 0


def _chunk_id(doc_id: str, index: int) -> str:
    return f"{doc_id}:c{index}"


def _make_chunk(
    doc_id: str,
    index: int,
    blocks: list[Block],
    authority_tier: int,
    source_type: str,
    asset_ids: list[str] | None = None,
) -> Chunk:
    text = "\n\n".join(b.text for b in blocks if b.text).strip()
    pages = [b.page for b in blocks]
    return Chunk(
        chunk_id=_chunk_id(doc_id, index),
        doc_id=doc_id,
        block_ids=[b.block_id for b in blocks],
        text=text,
        page_span=(min(pages), max(pages)) if pages else None,
        section_path=list(blocks[0].section_path) if blocks else [],
        authority_tier=authority_tier,
        source_type=source_type,
        asset_ids=list(asset_ids or []),
        token_count=estimate_tokens(text),
    )


#: Sentence boundary. The closing quote sits in the match rather than the lookbehind,
#: because Python requires a fixed-width lookbehind.
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"'”’]?\s+")


def split_long_block(block: Block, target_tokens: int) -> list[Block]:
    """Split a text block that is larger than a whole chunk, at sentence boundaries.

    The PDF adapter emits one block per run of prose, and a dense page can exceed the
    target on its own - which is how 42% of chunks ended up over 600 tokens on the first
    run. Splitting here rather than in the adapter keeps the block layer faithful to the
    document and makes chunk size purely a retrieval decision.
    """
    if block.block_type != "text" or block.token_count <= target_tokens:
        return [block]

    sentences = _SENTENCE_END.split(block.text)
    parts: list[Block] = []
    buffer: list[str] = []
    buffer_tokens = 0

    for sentence in sentences:
        tokens = estimate_tokens(sentence)
        if buffer and buffer_tokens + tokens > target_tokens:
            text = " ".join(buffer)
            parts.append(
                block.model_copy(
                    update={
                        "block_id": f"{block.block_id}.{len(parts)}",
                        "text": text,
                        "token_count": estimate_tokens(text),
                    }
                )
            )
            buffer, buffer_tokens = [], 0
        buffer.append(sentence)
        buffer_tokens += tokens

    if buffer:
        text = " ".join(buffer)
        parts.append(
            block.model_copy(
                update={
                    "block_id": f"{block.block_id}.{len(parts)}",
                    "text": text,
                    "token_count": estimate_tokens(text),
                }
            )
        )
    return parts or [block]


def _group_by_section(blocks: list[Block]) -> list[list[Block]]:
    """Consecutive blocks sharing a section path. Rule 2, enforced structurally."""
    groups: list[list[Block]] = []
    current: list[Block] = []
    current_key: tuple[str, ...] | None = None

    for block in blocks:
        key = tuple(block.section_path)
        if current and key != current_key:
            groups.append(current)
            current = []
        current.append(block)
        current_key = key
    if current:
        groups.append(current)
    return groups


def chunk_document(
    blocks: list[Block],
    doc_id: str,
    authority_tier: int,
    source_type: str,
    target_tokens: int = TARGET_TOKENS,
    overlap_ratio: float = OVERLAP_RATIO,
    stats: ChunkStats | None = None,
) -> list[Chunk]:
    """Chunk one document's blocks."""
    stats = stats if stats is not None else ChunkStats()
    chunks: list[Chunk] = []
    pending_short: list[Chunk] = []
    atomic_chunk_ids: set[str] = set()
    overlap_tokens = int(target_tokens * overlap_ratio)

    def emit(group: list[Block], assets: list[str] | None = None) -> None:
        if not group or not any(b.text.strip() for b in group):
            return
        chunk = _make_chunk(doc_id, len(chunks), group, authority_tier, source_type, assets)
        atomic = any(b.block_type in {"table", "figure"} for b in group)
        previous_atomic = bool(chunks) and chunks[-1].chunk_id in atomic_chunk_ids
        if chunk.token_count < MIN_TOKENS and not atomic:
            # A lone heading in its own section produced 1-token chunks on the first run.
            # Fold it forward if we can, otherwise drop it - a fragment that short cannot
            # answer anything and only dilutes the index.
            if chunks and not previous_atomic and chunks[-1].section_path == chunk.section_path:
                merged = chunks[-1].text + "\n\n" + chunk.text
                chunks[-1] = chunks[-1].model_copy(
                    update={
                        "text": merged,
                        "block_ids": chunks[-1].block_ids + chunk.block_ids,
                        "token_count": estimate_tokens(merged),
                    }
                )
            else:
                pending_short.append(chunk)
            return
        if pending_short and not atomic:
            # Attach any held-back heading to the chunk that follows it, which is the
            # content that heading actually introduces. Never to a table or figure -
            # rule 1 says those stand alone, and prepending prose to a table chunk is
            # exactly the contamination the rule exists to prevent.
            head = "\n\n".join(c.text for c in pending_short)
            pending_short.clear()
            merged = head + "\n\n" + chunk.text
            chunk = chunk.model_copy(
                update={"text": merged, "token_count": estimate_tokens(merged)}
            )
        if atomic:
            atomic_chunk_ids.add(chunk.chunk_id)
        chunks.append(chunk)

    for section_blocks in _group_by_section(blocks):
        buffer: list[Block] = []
        buffer_tokens = 0

        # Split to leave room for the overlap that will be prepended, otherwise a
        # full-size block plus carried overlap lands well over the target - that is
        # what kept 47% of chunks above 600 after the first fix.
        expanded: list[Block] = []
        for original in section_blocks:
            expanded.extend(split_long_block(original, target_tokens - overlap_tokens))

        for block in expanded:
            if block.block_type == "table":
                # Rule 1: a table is emitted alone, whatever it costs the token budget.
                emit(buffer)
                buffer, buffer_tokens = [], 0
                emit([block])
                stats.table_chunks += 1
                if block.token_count > target_tokens:
                    stats.oversized_tables += 1
                continue

            if block.block_type == "figure":
                # Rule 3: the VLM description stands alone.
                emit(buffer)
                buffer, buffer_tokens = [], 0
                emit([block], [block.asset_path] if block.asset_path else None)
                stats.figure_chunks += 1
                continue

            if buffer_tokens + block.token_count > target_tokens and buffer:
                emit(buffer)
                # Overlap: carry trailing blocks worth roughly `overlap_tokens`, so a
                # fact straddling the boundary survives whole in the next chunk too.
                # Only carry what FITS in the overlap budget. Stopping once the budget is
                # reached instead of before exceeding it dragged a whole 510-token block
                # across to satisfy a 90-token overlap, which is how chunks reached 1,078
                # tokens against a 600 target. Carrying nothing is a valid outcome.
                carried: list[Block] = []
                carried_tokens = 0
                for previous in reversed(buffer):
                    if carried_tokens + previous.token_count > overlap_tokens:
                        break
                    carried.insert(0, previous)
                    carried_tokens += previous.token_count
                buffer = carried
                buffer_tokens = carried_tokens

            buffer.append(block)
            buffer_tokens += block.token_count

        if buffer_tokens < MIN_TOKENS and chunks and buffer:
            # A trailing fragment is not worth its own embedding; fold it into the last
            # chunk of the same section rather than indexing a two-line orphan - unless
            # that chunk is a table or figure, which stand alone by rule 1.
            last = chunks[-1]
            if last.chunk_id not in atomic_chunk_ids and last.section_path == list(
                buffer[0].section_path
            ):
                merged = last.text + "\n\n" + "\n\n".join(b.text for b in buffer)
                chunks[-1] = last.model_copy(
                    update={
                        "text": merged,
                        "block_ids": last.block_ids + [b.block_id for b in buffer],
                        "token_count": estimate_tokens(merged),
                    }
                )
                buffer = []
        emit(buffer)

    if pending_short:
        # Anything still held back never found a chunk to join - a short paragraph that
        # sits alone before a table, say. Emit it rather than lose it: an undersized
        # chunk is a minor cost, silently dropping corpus text is not.
        text = "\n\n".join(c.text for c in pending_short)
        chunks.append(
            Chunk(
                chunk_id=_chunk_id(doc_id, len(chunks)),
                doc_id=doc_id,
                block_ids=[b for c in pending_short for b in c.block_ids],
                text=text,
                page_span=pending_short[0].page_span,
                section_path=pending_short[0].section_path,
                authority_tier=authority_tier,
                source_type=source_type,
                token_count=estimate_tokens(text),
            )
        )
        pending_short.clear()

    stats.chunks += len(chunks)
    stats.documents += 1
    return chunks


def _image_chunks(settings: Settings, start_index: int) -> list[Chunk]:
    """Fold described images in as standalone chunks.

    Their `searchable_text` already renders `values[]` as explicit `label: value` lines,
    so the label-to-number binding that defeats the Emberdeep trap survives into the
    index rather than being flattened back into prose.
    """
    path = settings.index_dir / "images.jsonl"
    if not path.exists():
        return []

    chunks: list[Chunk] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        text = record.get("searchable_text") or record.get("description") or ""
        if not text.strip():
            continue
        chunks.append(
            Chunk(
                chunk_id=f"img:{record['asset_id']}",
                doc_id=record["canonical_path"],
                block_ids=[record["asset_id"]],
                text=text,
                page_span=None,
                section_path=[record.get("caption", "")],
                authority_tier=record["authority_tier"],
                source_type=record["source_type"],
                asset_ids=[record["asset_id"]],
                token_count=estimate_tokens(text),
            )
        )
    return chunks


def run(settings: Settings | None = None, target_tokens: int = TARGET_TOKENS) -> ChunkStats:
    settings = settings or get_settings()
    documents_path = settings.index_dir / "documents.jsonl"
    blocks_path = settings.index_dir / "blocks.jsonl"
    if not documents_path.exists() or not blocks_path.exists():
        raise FileNotFoundError("run `python -m src.ingestion.pipeline` first")

    documents = {
        row["doc_id"]: row
        for row in map(json.loads, documents_path.read_text(encoding="utf-8").splitlines())
    }

    by_doc: dict[str, list[Block]] = {}
    for line in blocks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        block = Block(**json.loads(line))
        by_doc.setdefault(block.doc_id, []).append(block)

    stats = ChunkStats()
    all_chunks: list[Chunk] = []
    for doc_id, blocks in by_doc.items():
        meta = documents.get(doc_id, {})
        all_chunks.extend(
            chunk_document(
                blocks,
                doc_id,
                meta.get("authority_tier", 4),
                meta.get("source_type", "unknown"),
                target_tokens=target_tokens,
                stats=stats,
            )
        )

    images = _image_chunks(settings, len(all_chunks))
    stats.figure_chunks += len(images)
    stats.chunks += len(images)
    all_chunks.extend(images)

    target = settings.index_dir / "chunks.jsonl"
    tmp = target.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(c.model_dump_json() + "\n" for c in all_chunks), encoding="utf-8")
    tmp.replace(target)
    return stats


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-tokens", type=int, default=TARGET_TOKENS)
    args = parser.parse_args()

    settings = get_settings()
    stats = run(settings, target_tokens=args.target_tokens)
    print(f"chunks          : {stats.chunks}")
    print(f"  table chunks  : {stats.table_chunks}")
    print(f"  figure chunks : {stats.figure_chunks}")
    print(f"  oversized tbl : {stats.oversized_tables} (kept whole regardless)")
    print(f"documents       : {stats.documents}")
    print(f"\nwrote {settings.index_dir / 'chunks.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
