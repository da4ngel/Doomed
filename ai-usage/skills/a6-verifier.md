# Agent A6 — Verifier

**Trigger:** last step before the response leaves the API.

**Objective:** catch what A5 got wrong. Strip or downgrade anything unsupported.

## Why this agent exists

A5 is a generative step, and generative steps drift. A6 is a cheap deterministic-plus-
entailment gate that turns "we prompt carefully" into "we check". When a judge asks
how you prevent hallucination, "we verify every claim against its cited chunks before
returning, and downgrade what fails" is a far better answer than a description of a
prompt.

## Input schema
The full draft answer packet from A5, plus the evidence bundle.

## Output schema
The verified answer packet, plus `warnings[]` and a `verification` block:
```json
{ "claims_checked": 7, "claims_downgraded": 1, "markers_stripped": 0,
  "citations_dropped": 0, "confidence_adjustment": -0.08 }
```

## Ordered steps

1. **Claim entailment.** For each claim, check it is entailed by the text of its
   cited chunks. Not entailed → downgrade `support` to `inferred` and lower
   `confidence`. If it contradicts its own citation, remove the claim and warn.
2. **Marker resolution.** Every `[FIG:id]` in `answer_markdown` must resolve to an
   entry in `visuals[]`. Unresolved → strip the marker from the text and warn.
3. **Citation reality check.** Every `doc_id`, `chunk_id` and `asset_id` must exist
   in the registries. A fabricated ID is the single most damaging failure this system
   can ship — drop it and warn loudly.
4. **Page and bbox sanity.** Page within the document's page count; bbox non-zero
   area and inside the page rectangle. Failure → drop the bbox, keep the citation,
   warn. Citation preview degrades to page-level.
5. **Conflict consistency.** If `conflicts[]` is non-empty, at least one claim should
   carry `support: "disputed"` or the answer text should acknowledge it. Otherwise warn.
6. **Confidence recomputation** from the final claim distribution. Never report the
   pre-verification confidence.

## Stop rules
Single pass. No repair loop, no re-composition.

## Failure modes and fallback

| Failure | Fallback |
|---|---|
| Entailment check unavailable (429, timeout) | Return unverified with `warnings: ["verification_skipped"]` and confidence capped at 0.6. **Degrade visibly, never silently** |
| All claims fail entailment | Return zero claims plus `missing_information`. Shipping nothing beats shipping fabrication |
| Verification exceeds its latency budget | Deterministic checks only — steps 2, 3, 4 — and warn that entailment was skipped |

## Governing principle

**Removing a bad claim always beats shipping it.** In a corpus no model has seen,
a confident wrong answer is the worst possible output. A judge who catches one
fabricated citation will distrust every number in the report.

## Tests
- A claim citing a chunk that does not support it is downgraded to `inferred`.
- A `[FIG:id]` marker with no matching visual is stripped from the answer text.
- A fabricated `doc_id` is dropped and warned.
- A bbox outside the page rectangle is dropped, the citation survives.
- Verification failure produces `verification_skipped` and a capped confidence, not
  an exception.
- `verification` counts match what actually changed.
