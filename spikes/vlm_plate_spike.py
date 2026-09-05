"""THROWAWAY SPIKE. Answers one question: can a free vision model read the plates?

This is not a pipeline and must not grow into one. It exists to de-risk the single
largest block of the dev set before any ingestion code is written.

The question it answers
-----------------------
11 of the 20 dev questions are sub-track 1A, and the corpus findings established that
those answers exist *only* inside the 85 PNGs - `1a_009` asks for Greyfell Citadel's
garrison strength and `3,695` appears in no document, only in the plate.

Worse, `plate_01_location_emberdeep.png` is a planted trap. It is a bar chart carrying
three reference values (800 Old Imperial minimum, 2,400 Border-march standard, 6,000
Great Keep standard) alongside the actual Emberdeep figure of 1,114. Tesseract read the
reference values and rendered the answer itself as "Ee". Any pipeline that OCRs the
plate and hands flat text to an LLM will confidently answer 6,000.

So the requirement is figure *understanding*, not figure text extraction: the model must
bind each value to its label. This spike checks whether a free model can actually do it.

If it cannot, the fallback is OCR plus bounding-box spatial layout, feeding the model
"label at (x,y) = value at (x,y)" pairs instead of flat text - and that decision needs
to be made today, not on Sunday.

Run:  uv run python spikes/vlm_plate_spike.py [--model MODEL] [--all-models]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings  # noqa: E402
from src.core.llm import LLMClient, NoProviderConfiguredError  # noqa: E402
from src.ingestion import images  # noqa: E402

#: (provider, model) pairs, cheapest first. Paired because a model id is not portable:
#: "gpt-4o-mini" is a 404 on OpenRouter, which spells it "openai/gpt-4o-mini".
#:
#: These ids ROT. The first run of this spike failed with three 404s because every
#: hardcoded free model had been retired. Use --discover to re-derive the free tier
#: from the live catalogue instead of trusting this list.
CANDIDATE_MODELS: list[tuple[str, str]] = [
    ("openrouter", "google/gemma-4-31b-it:free"),
    ("openrouter", "minimax/minimax-m3:free"),
    ("openrouter", "thinkingmachines/inkling:free"),
    ("openai", "gpt-4o-mini"),
    ("openai", "gpt-4o"),
]


def discover_free_vision_models(limit: int = 6) -> list[tuple[str, str]]:
    """Ask OpenRouter which free models actually accept image input, right now."""
    import httpx

    settings = get_settings()
    response = httpx.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        timeout=60.0,
    )
    response.raise_for_status()
    found = [
        ("openrouter", m["id"])
        for m in response.json()["data"]
        if "image" in (m.get("architecture") or {}).get("input_modalities", [])
        and m["id"].endswith(":free")
    ]
    return sorted(found)[:limit]


# The prompt lives in the pipeline, not here, so the text that was validated is the
# exact text that ships. Re-running this spike re-tests the real prompt.
INSTRUCTION = images.INSTRUCTION


@dataclass
class Case:
    relative_path: str
    expects: str
    why_it_matters: str

    def contains_answer(self, blob: str) -> bool:
        needle = self.expects.lower()
        haystack = blob.lower()
        if needle in haystack:
            return True
        # "1,114" and "1114" are the same answer.
        return needle.replace(",", "") in haystack.replace(",", "")


CASES = [
    Case(
        "images/plate_01_location_emberdeep.png",
        "1114",
        "THE TRAP: chart with 800/2,400/6,000 reference values. Flat OCR answers 6,000.",
    ),
    Case(
        "images/plate_09_location_greyfell_citadel.png",
        "3695",
        "Easy case. If this fails, the model cannot read plates at all.",
    ),
    Case(
        "wiki/images/atmo_portrait_character_ignatz_ashgrove_the_oathless.png",
        "scroll",
        "atmo_* images yield ZERO OCR characters. Vision is the only path.",
    ),
]


def run_case(client: LLMClient, case: Case, provider: str, model: str) -> dict[str, object]:
    path = get_settings().corpus_root / case.relative_path
    if not path.exists():
        return {"case": case.relative_path, "error": f"missing image: {path}"}

    try:
        response = client.describe_image(
            path, INSTRUCTION, model=model, provider=provider, json_mode=True
        )
    except Exception as exc:  # noqa: BLE001 - a spike reports failures, it does not raise
        return {
            "case": case.relative_path,
            "model": f"{provider}:{model}",
            "error": f"{type(exc).__name__}: {exc}",
        }

    blob = response.text
    try:
        parsed = response.json_payload()
        blob = json.dumps(parsed)
    except (json.JSONDecodeError, ValueError):
        parsed = None

    return {
        "case": case.relative_path,
        "model": model,
        "provider": response.provider,
        "passed": case.contains_answer(blob),
        "expects": case.expects,
        "tokens_in": response.tokens_in,
        "tokens_out": response.tokens_out,
        "cost_usd": response.cost_usd,
        "latency_ms": response.latency_ms,
        "cached": response.cached,
        "parsed": parsed,
        "raw_text": response.text,
    }


def report(results: list[dict[str, object]]) -> bool:
    print("\n" + "=" * 78)
    print("VLM PLATE SPIKE")
    print("=" * 78)

    all_passed = True
    for result, case in zip(results, CASES, strict=False):
        print(f"\n--- {result['case']}")
        print(f"    why: {case.why_it_matters}")
        if "error" in result:
            print(f"    ERROR: {result['error']}")
            all_passed = False
            continue

        verdict = "PASS" if result["passed"] else "FAIL"
        print(f"    expects: {result['expects']}   ->   {verdict}")
        print(
            f"    model={result['model']} provider={result['provider']} "
            f"tokens={result['tokens_in']}/{result['tokens_out']} "
            f"cost=${result['cost_usd']:.5f} {result['latency_ms']}ms "
            f"{'(cached)' if result['cached'] else ''}"
        )
        if result["parsed"]:
            values = result["parsed"].get("values") if isinstance(result["parsed"], dict) else None
            if values:
                print("    values read:")
                for entry in values:
                    print(f"      - {entry}")
        else:
            print(f"    raw: {str(result['raw_text'])[:400]}")
        all_passed = all_passed and bool(result["passed"])

    print("\n" + "-" * 78)
    if all_passed:
        print("VERDICT: the plan holds. VLM figure description stays P0 for D1 morning.")
    else:
        print("VERDICT: escalate. Try the next free model, then Gemini, then Bedrock.")
        print("         If nothing reads the chart, fall back to OCR + bbox spatial")
        print("         layout: feed the model 'label@(x,y) = value@(x,y)' pairs.")
    print("Record the outcome as ADR-002 either way.")
    print("-" * 78)
    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="single model to test")
    parser.add_argument("--provider", default="openrouter", help="provider for --model")
    parser.add_argument("--all-models", action="store_true", help="walk the escalation ladder")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="re-derive free vision models from the live catalogue instead of the list",
    )
    args = parser.parse_args()

    try:
        client = LLMClient()
    except NoProviderConfiguredError as exc:
        print(f"\n{exc}\n")
        return 2

    if not client.available_providers():
        print(f"\n{NoProviderConfiguredError()}\n")
        return 2
    print(f"providers configured: {', '.join(client.available_providers())}")

    if args.model:
        ladder = [(args.provider, args.model)]
    elif args.discover:
        ladder = discover_free_vision_models()
        print(f"discovered {len(ladder)} free vision models from the live catalogue")
    elif args.all_models:
        ladder = CANDIDATE_MODELS
    else:
        ladder = [("openrouter", get_settings().llm_model_vision)]

    # Only try providers that actually have credentials, so the ladder does not spend
    # its steps on 401s from a provider we never configured.
    available = set(client.available_providers())
    ladder = [(p, m) for p, m in ladder if p in available]
    if not ladder:
        print("\nNo candidate model matches a configured provider.\n")
        return 2

    for provider, model in ladder:
        print(f"\n### {provider} : {model}")
        results = [run_case(client, case, provider, model) for case in CASES]
        if report(results):
            return 0
        if (provider, model) != ladder[-1]:
            print("\n>>> escalating to the next model in the ladder\n")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
