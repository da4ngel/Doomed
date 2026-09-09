# Agent A1 — Query Analyst

**Trigger:** every incoming question, before any retrieval.

**Objective:** normalise the question without destroying invented proper nouns,
classify its intent, decompose it into sub-questions, and link seed entities.

**Tools:** entity vocabulary lookup, alias table. No LLM call for normalisation —
LLM only for decomposition and intent.

## Why this agent exists

The archive is entirely invented. Standard spell-correction has never seen
"Veyra Sunder" and will helpfully convert it to something real, at which point
retrieval collapses. Judges will misspell names. Every other team will silently
mangle them.

The fix: fuzzy-match **only against the entity vocabulary extracted from the corpus**,
never against a general dictionary. Show the correction. Allow rollback.

## Input schema
```json
{ "question": "string", "conversation_id": "string|null", "mode_hint": "auto|rich|graph|agent" }
```

## Output schema
```json
{
  "normalized": "string",
  "corrections": [
    { "from": "Vera Sundry", "to": "Veyra Sunder", "score": 0.91, "entity_id": "e_224" }
  ],
  "intent": "direct|visual|comparison|multi_hop|contradiction|exploratory",
  "sub_questions": ["string"],
  "seed_entities": [{ "entity_id": "e_224", "surface": "Veyra Sunder", "type": "Character" }],
  "requires_visual": true,
  "confidence": 0.0
}
```

## Ordered steps

1. Tokenise. Extract candidate proper nouns: capitalised tokens, multi-word
   capitalised spans, and any token absent from a common-English word list.
2. For each candidate, fuzzy-match against the entity vocabulary and alias table.
   Accept a correction only above the similarity threshold. **Never correct a token
   that already matches an entity exactly.**
3. Classify intent. `visual` when the question asks what something looks like, or
   names a figure, plate, diagram, map or table. `multi_hop` when two or more
   distinct entities appear, or the question asks what is affected by, connected to,
   or downstream of something. `contradiction` when it asks whether sources agree.
4. Decompose into sub-questions only when intent is `multi_hop`, `comparison` or
   `exploratory`. A direct lookup gets exactly one sub-question: itself.
5. Emit seed entities for A2's graph tools.

## Stop rules
Single pass. No loop. No retry.

## Failure modes and fallback

| Failure | Fallback |
|---|---|
| Fuzzy match below threshold | Pass the token through unchanged. Emit `warnings: ["normalization_skipped"]`. **Never silently rewrite a name.** |
| Entity vocabulary not yet built (pre-D3) | Skip step 2 entirely; intent classification still runs |
| Decomposition returns nothing | Use the normalised question as the single sub-question |
| Question is empty or whitespace | Return `intent: "direct"` with empty sub-questions; the orchestrator short-circuits to a clarification response |

## Tests
- A known entity spelled correctly produces zero corrections.
- A known entity with one character transposed is corrected, and `corrections[]`
  names both forms.
- A real English word that resembles an entity is **not** corrected.
- A two-entity question classifies as `multi_hop`.
- "What does the Concord seal look like" classifies as `visual` with
  `requires_visual: true`.
- A 5,000-character question does not crash and returns within the latency budget.
