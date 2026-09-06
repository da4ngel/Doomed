"""Run real chat acceptance via HTTP; refuse to score an unavailable knowledge service.

Usage: python -m tests.reasoning.acceptance --preflight-only --out /tmp/ashen-acceptance
Gold answers never enter API requests. Lexical matches are diagnostic, not correctness.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.api.schemas import AnswerPacket, EntityVocabularyResponse
from src.core.cache import ResponseCache
from src.core.retry import RetryPolicy, call_with_retry

SUITES = Path(__file__).resolve().parents[2] / "eval/suites"


class LiveHTTP:
    """Journal each exchange through core.cache; live status reads must never be stale.

    One attempt prevents an ambiguous failed POST from starting multiple paid jobs.
    Fresh cache keys record observations without reusing old readiness/trace results.
    """

    def __init__(
        self, base_url: str, cache: ResponseCache, transport: httpx.BaseTransport | None = None
    ) -> None:
        url = httpx.URL(base_url)
        if url.scheme not in {"http", "https"} or url.userinfo or url.query:
            raise ValueError("API URL must be an HTTP(S) origin without credentials or query")
        self.base_url, self.cache, self.transport = base_url.rstrip("/"), cache, transport

    def request(self, method: str, path: str, body: dict | None = None) -> Any:
        url = self.base_url + path

        def fetch() -> str:
            with httpx.Client(timeout=5, transport=self.transport) as client:
                response = client.request(method, url, json=body)
                response.raise_for_status()
                return json.dumps(response.json())

        raw = self.cache.get_or_set(
            "live-acceptance",
            url,
            {
                "method": method,
                "body": body,
                "observation": uuid.uuid4().hex,
            },
            lambda: call_with_retry(fetch, policy=RetryPolicy(max_attempts=1)),
        )
        return json.loads(raw)


def preflight(knowledge: LiveHTTP, chat: LiveHTTP) -> dict:
    checks, blockers = {}, []
    for name, client, path in [
        ("knowledge", knowledge, "/v1/ready"),
        ("vocabulary", knowledge, "/v1/graph/entities?limit=1000"),
        ("chat", chat, "/openapi.json"),
    ]:
        try:
            data = client.request("GET", path)
            if name == "knowledge":
                checks[name] = {
                    key: data.get(key) for key in ["status", "chunks", "entities", "warm"]
                }
                if data.get("status") != "ready" or not data.get("chunks"):
                    blockers.append("Knowledge API is not ready with a nonempty index")
            elif name == "vocabulary":
                vocabulary = EntityVocabularyResponse.model_validate(data)
                named = sum(e.type != "Title" for e in vocabulary.entities)
                checks[name] = {
                    "total": vocabulary.total,
                    "returned": len(vocabulary.entities),
                    "named_entities": named,
                }
                if not named or vocabulary.total != len(vocabulary.entities):
                    blockers.append("Entity vocabulary is empty or truncated")
            else:
                paths = data.get("paths", {})
                checks[name] = {
                    "title": data.get("info", {}).get("title"),
                    "jobs": "/v1/chat/jobs" in paths,
                }
                if "/v1/chat/jobs" not in paths:
                    blockers.append("Chat service does not expose background jobs")
                if "fixture" in str(data.get("info", {}).get("title", "")).casefold():
                    blockers.append("A scripted fixture is not a real acceptance target")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            checks[name] = {"error": type(error).__name__}
            blockers.append(f"{name} preflight failed: {type(error).__name__}")
    return {"checks": checks, "blockers": blockers, "ready": not blockers}


def lexical_match(claim_text: str, accepted: list[str]) -> bool:
    """Never award a match for 94 inside 194 or from a conflict/missing-info paragraph."""

    def normalized(text: str) -> str:
        return " ".join(
            text.casefold().replace(",", "").replace("‑", "-").replace("-", " ").split()
        )

    text = normalized(claim_text)
    return any(
        re.search(r"(?<!\w)" + re.escape(normalized(a)) + r"(?!\w)", text)
        for a in accepted
        if a.strip()
    )


def score_packet(packet: AnswerPacket, row: dict) -> dict:
    citations = {c.id: c for c in packet.citations}
    supported = [c for c in packet.claims if c.support != "inferred"]
    markers = re.findall(r"\[FIG:([^\]]+)\]", packet.answer_markdown)
    errors = []
    if any(
        not c.citation_ids or any(i not in citations for i in c.citation_ids) for c in packet.claims
    ):
        errors.append("claim_citation_unresolved")
    if any(
        c.excerpt_sha256 != hashlib.sha256(c.excerpt.encode()).hexdigest() for c in packet.citations
    ):
        errors.append("citation_hash_mismatch")
    if set(markers) - {v.id for v in packet.visuals}:
        errors.append("figure_marker_unresolved")
    if packet.partial and not packet.missing_information:
        errors.append("partial_without_missing_information")
    accepted = row.get("accept") or ([row["gold_answer"]] if row.get("gold_answer") else [])
    gold = set(row.get("gold_docs", []) + row.get("gold_assets", []))
    cited = {c.doc_id for c in packet.citations}
    return {
        "qid": row["qid"],
        "structural_errors": errors,
        "lexical_answer_match": (
            any(lexical_match(c.text, accepted) for c in supported) if accepted else None
        ),
        "groundedness": packet.groundedness(),
        "claims": len(packet.claims),
        "empty_answer": not supported,
        "partial": packet.partial,
        "citation_recall": len(gold & cited) / len(gold) if gold else None,
        "citation_precision": len(gold & cited) / len(cited) if gold and cited else None,
        "iterations": packet.iterations,
        "manual_review_required": True,
    }


def run_question(chat: LiveHTTP, row: dict, directory: Path, timeout: float = 90) -> dict:
    started = time.monotonic()
    # The only model-facing input is the question; no gold answer/quote/labels.
    job = chat.request(
        "POST", "/v1/chat/jobs", {"question": row["question"], "mode": "auto", "budget": 6}
    )
    trace_id = job["trace_id"]
    while time.monotonic() - started < timeout:
        trace = chat.request("GET", f"/v1/traces/{trace_id}")
        if trace.get("packet") is not None:
            packet = AnswerPacket.model_validate(trace["packet"])
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "trace.json").write_text(json.dumps(trace, indent=2))
            (directory / "answer.md").write_text(packet.answer_markdown)
            return {
                **score_packet(packet, row),
                "trace_id": trace_id,
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
        if trace.get("status") != "running":
            raise RuntimeError("Trace ended without a packet")
        time.sleep(0.5)
    raise TimeoutError("Chat job did not complete before acceptance deadline")


def load_questions(suite: str) -> list[dict]:
    names = ["rich_1a", "multihop_1b", "contradiction_1c"] if suite == "dev" else [suite]
    return [
        row
        for name in names
        for row in json.loads((SUITES / f"{name}.json").read_text())["questions"]
    ]


def write_report(directory: Path, report: dict) -> None:
    (directory / "report.json").write_text(json.dumps(report, indent=2))
    lines = [
        f"# Acceptance run: {report['status']}",
        "",
        "This report contains observed checks, not inferred readiness or model-judged correctness.",
        "",
    ]
    lines += [f"- Blocker: {b}" for b in report["preflight"]["blockers"]]
    lines += [
        "",
        f"Questions attempted: {len(report['results'])}",
        "Lexical answer matches require human review, including negation "
        "and exact subject binding.",
    ]
    (directory / "report.md").write_text("\n".join(lines) + "\n")
    with (directory / "human-review.csv").open("w", newline="") as handle:
        fields = ["qid", "correctness_0_3", "refusal_correct", "notes"]
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        writer.writerows({"qid": row["qid"]} for row in report["results"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-url", default="http://127.0.0.1:8000")
    parser.add_argument("--chat-url", default="http://127.0.0.1:8001")
    parser.add_argument("--suite", choices=["dev", "unanswerable"], default="dev")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("/tmp/ashen-acceptance"))
    args = parser.parse_args()
    directory = args.out / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    )
    directory.mkdir(parents=True)
    cache = ResponseCache(directory / "http-journal.sqlite")
    knowledge, chat = LiveHTTP(args.knowledge_url, cache), LiveHTTP(args.chat_url, cache)
    checks = preflight(knowledge, chat)
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "preflight": checks,
        "suite": args.suite,
        "question_source": "checked-in human-authored gold suite text",
        "status": "blocked" if not checks["ready"] else "preflight_ready",
        "results": [],
    }
    if checks["ready"] and not args.preflight_only:
        for row in load_questions(args.suite):
            try:
                result = run_question(chat, row, directory / row["qid"])
            except Exception as error:
                result = {"qid": row["qid"], "error": type(error).__name__}
            report["results"].append(result)
        report["status"] = (
            "completed_with_errors"
            if any("error" in r for r in report["results"])
            else "manual_review_required"
        )
    write_report(directory, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(directory / "report.md"),
                "attempted": len(report["results"]),
            }
        )
    )
    return 2 if report["status"] in {"blocked", "completed_with_errors"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
