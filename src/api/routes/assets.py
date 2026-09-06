"""GET /v1/assets/{id} and /v1/assets/{id}/meta — serving the figures.

WHY this endpoint carries weight beyond plumbing: sub-track 1A is answered by images, and
`[FIG:asset_id]` markers in an answer resolve to these URLs. A citation a judge cannot
open is a citation they cannot check.

The corpus is READ-ONLY, so images are streamed from it rather than copied. The asset id
is a content hash, which means the two byte-identical copies of each plate
(`images/` and `codex/images/`) resolve to one asset and one URL.
"""

from __future__ import annotations

import json
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.core.config import get_settings

router = APIRouter(tags=["09 Assets"])


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict]:
    """asset_id -> record, loaded once from images.jsonl."""
    path = get_settings().index_dir / "images.jsonl"
    if not path.exists():
        return {}
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            records[record["asset_id"]] = record
    return records


def _record_or_404(asset_id: str) -> dict:
    record = _registry().get(asset_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"unknown asset {asset_id!r} - "
                "run `python -m src.ingestion.images` if the registry is empty"
            ),
        )
    return record


@router.get("/v1/assets/{asset_id}")
def get_asset(asset_id: str) -> FileResponse:
    """Stream the image itself, straight from the read-only corpus."""
    record = _record_or_404(asset_id)
    path = get_settings().corpus_root / record["canonical_path"]
    if not path.exists():
        raise HTTPException(status_code=410, detail=f"asset file missing: {path.name}")
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.get("/v1/assets/{asset_id}/meta")
def get_asset_meta(asset_id: str) -> dict:
    """The structured description, including the label/value pairs read off a chart.

    `values` is the field that makes a figure answerable: it binds each number to the
    label it belongs to, so "Emberdeep" resolves to 1,114 rather than to the larger
    reference bar printed beside it.
    """
    record = _record_or_404(asset_id)
    return {
        "asset_id": record["asset_id"],
        "canonical_path": record["canonical_path"],
        "paths": record["paths"],
        "caption": record["caption"],
        "entity_link": record["entity_link"],
        "kind": record["kind"],
        "subject": record["subject"],
        "values": record["values"],
        "objects_depicted": record["objects_depicted"],
        "description": record["description"],
        "authority_tier": record["authority_tier"],
        "source_type": record["source_type"],
        "model": record["model"],
        "url": f"/v1/assets/{record['asset_id']}",
    }


@router.get("/v1/assets")
def list_assets(limit: int = 20, kind: str | None = None) -> dict:
    """Browse the registry. Useful for finding an asset id to test with."""
    records = list(_registry().values())
    if kind:
        records = [r for r in records if r["kind"] == kind]
    return {
        "total": len(_registry()),
        "returned": min(limit, len(records)),
        "assets": [
            {
                "asset_id": r["asset_id"],
                "caption": r["caption"],
                "kind": r["kind"],
                "has_values": bool(r["values"]),
                "url": f"/v1/assets/{r['asset_id']}",
            }
            for r in records[:limit]
        ],
    }
