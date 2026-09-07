"""Exact subject matching and label binding keep chart distractors out of answers."""

from __future__ import annotations

import re
from typing import Any

from src.api.schemas import SearchHit, Visual


def words(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def subject_names(asset: dict[str, Any]) -> list[str]:
    link = str(asset.get("entity_link") or "").removeprefix("ent_").replace("_", " ")
    names = [words(link), words(str(asset.get("subject") or ""))]
    return [n.removeprefix("the ") for n in names if len(n) >= 3]


def subject_matches(asset: dict[str, Any], text: str) -> bool:
    haystack = " " + words(text) + " "
    return any(" " + name + " " in haystack for name in subject_names(asset))


def score_asset(asset: dict[str, Any], question: str, claim: str) -> float:
    if not subject_matches(asset, question) or not subject_matches(asset, claim):
        return 0.0
    return 0.95 if asset.get("values") else 0.85


def bound_value(asset: dict[str, Any], claim: str, excerpt: str) -> bool:
    """A matching number alone is insufficient: its subject label must be cited."""
    numbers = set(re.findall(r"\d+(?:[,.]\d+)*", claim))
    if not numbers or not asset.get("values"):
        return True
    for row in asset["values"]:
        label, value = str(row.get("label", "")), str(row.get("value", ""))
        if (
            subject_matches(asset, label)
            and words(label) in words(excerpt)
            and value in excerpt
            and numbers <= set(re.findall(r"\d+(?:[,.]\d+)*", value))
        ):
            return True
    return False


def make_visual(asset: dict[str, Any], chunk: SearchHit, score: float) -> Visual:
    asset_id = asset["asset_id"]
    return Visual(
        id=asset_id,
        type="table" if asset.get("kind") == "table" else "figure",
        url=f"/v1/assets/{asset_id}",
        caption=str(asset.get("caption") or ""),
        doc_id=chunk.doc_id,
        page=chunk.page,
        relevance=score,
        why=f"Shows the cited evidence for {asset.get('subject') or chunk.title}.",
    )
