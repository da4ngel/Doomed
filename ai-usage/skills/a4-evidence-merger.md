# Agent A4 — Evidence Merger

**Trigger:** the loop has stopped. Before composition.

**Objective:** deduplicate evidence, cluster assertions, detect contradictions, and
resolve them by authority tier — or refuse to resolve and surface both.

## Why this agent wins marks

The challenge document says the archive's sources *"differ in reliability: a tavern
ballad and an official codex entry do not always agree."* It is a stated property of
the corpus and almost nobody will build for it. Everyone else will average
contradictory sources into a confident, wrong sentence.

## Input schema
```json
{
  "question": "string",
  "chunks": [{ "chunk_id": "", "text": "", "doc_id": "", "page": 0,
               "authority_tier": 1, "source_type": "codex" }],
  "subgraph": { "nodes": [], "edges": [] },
  "hop_order": ["chunk_id sequence, for multi-hop presentation"]
}
```

## Output schema
```json
{
  "evidence_bundle": [{ "chunk_id": "", "text": "", "authority_tier": 1,
                        "hop": 1, "role": "primary|supporting|contradicting" }],
  "conflicts": [
    { "attribute": "Concord dissolution year",
      "claim_a": "412 AE", "sources_a": ["codex_02 p88", "ledger_044"], "tier_a": 1,
      "claim_b": "419 AE", "sources_b": ["ballad_017"],                 "tier_b": 5,
      "resolution": "tier_1_corroborated|tier_preferred|unresolved",
      "rationale": "one sentence" }
  ],
  "reliability_notes": ["The only source for the fourth house is a tier-5 ballad."]
}
```

## Ordered steps
1. Deduplicate by `chunk_id`, then by near-identical text — the same fact often
   appears in the wiki and the codex with minor rewording.
2. Extract atomic assertions and cluster them by `(entity, attribute)`.
3. Within each cluster, flag clusters holding incompatible values.
4. Resolve:
   - **different tiers** → prefer the lower tier number; `resolution: "tier_preferred"`
   - **lower tier corroborated by a second independent document** →
     `resolution: "tier_1_corroborated"`, higher confidence
   - **equal tiers, no corroboration** → `resolution: "unresolved"`. **Do not pick.**
     Surface both. This behaviour is a feature; state it in the report
5. Order the bundle by hop for multi-hop questions so the answer reads as a chain.
6. Write `reliability_notes` for any answer resting solely on tier 4 or 5.

## Stop rules
Deterministic, single pass. No loop, no retry.

## Failure modes and fallback

| Failure | Fallback |
|---|---|
| Assertion extraction fails on a chunk | Keep the chunk as `role: "supporting"` and skip its conflict analysis. Never drop evidence |
| Every source is tier 5 | Return the bundle with a `reliability_notes` entry. The composer must say so in the answer |
| Two tier-1 sources contradict | `resolution: "unresolved"`. A tier-1 disagreement is a genuine finding — say so |

## Tests
- Two chunks stating different years for the same event produce exactly one conflict.
- A tier-1 vs tier-5 conflict resolves to the tier-1 claim with a rationale naming the tier.
- Two tier-3 sources in conflict produce `resolution: "unresolved"` with both surfaced.
- Near-duplicate wiki and codex text deduplicates to one bundle entry, keeping the
  lower tier.
- Multi-hop input produces a bundle ordered by hop.
