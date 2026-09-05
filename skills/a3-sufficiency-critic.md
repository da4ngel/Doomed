# Agent A3 — Sufficiency Critic

**Trigger:** after every A2 call.

**Objective:** decide whether the evidence gathered so far can answer the question.
If not, name precisely what is missing and choose the next action **using what was
just learned**.

## Why this agent is the centre of sub-track 1C

The challenge document describes this component almost literally: *"a human expert
reads what they find, learns from it, realises what's still missing, and goes looking
for more — reasoning between each step."*

Most teams will implement a loop that re-runs search with a rephrased query. That is
churn. The difference is that A3 must use **newly discovered facts** to form the next
query — an entity name that only appeared in step 2 becomes the search term in step 3.
That is what `gain_per_step` measures and what the trace panel makes visible on video.

## Input schema
```json
{
  "question": "string",
  "sub_questions": ["string"],
  "evidence_so_far": [{ "chunk_id": "", "text": "", "authority_tier": 1, "from_step": 1 }],
  "entities_discovered": [{ "entity_id": "", "canonical_name": "", "first_seen_step": 2 }],
  "steps_taken": 2,
  "budget": { "max_steps": 6, "max_tokens": 60000, "max_wall_ms": 25000 },
  "steps_without_new_evidence": 0
}
```

## Output schema
```json
{
  "sufficient": false,
  "covered": ["which sub-questions the current evidence answers"],
  "missing": ["the fourth and fifth signatory houses are not named in anything retrieved"],
  "next_action": "graph_neighbors",
  "next_query": "Ashfall Concord signatory",
  "next_args": { "entity_id": "e_311", "hops": 2 },
  "reason": "Step 2 surfaced 'Concord signatories' as a relation type; the graph is the direct path to the remaining three.",
  "confidence": 0.74
}
```

## Ordered steps
1. Map each sub-question to the evidence that addresses it. Anything unmapped goes
   into `missing[]` **in concrete terms** — a named gap, not "more information needed."
2. If every sub-question is covered by at least one chunk, set `sufficient: true`.
3. Otherwise choose the next action from what was *just* learned:
   - a new entity name appeared → `hybrid_search` or `list_mentions` on that name
   - two known entities need connecting → `graph_paths`
   - one entity needs its surroundings → `graph_neighbors`
   - the question needs a figure and none has been retrieved → `figure_search`
   - a chunk is visibly truncated mid-fact → `read_section`
4. Write `reason` as one sentence naming the fact from the previous step that drove
   the choice. This string is rendered in the trace panel and appears on video.

## Stop rules
Return `sufficient: true` when every sub-question is covered, **or** the orchestrator
halts on any of: `steps_taken >= 6`, token cap, wall-clock cap, or
`steps_without_new_evidence >= 2`.

## Failure modes and fallback

| Failure | Fallback |
|---|---|
| Budget exhausted, coverage incomplete | Hand to A5 with `partial: true` and the unresolved `missing[]`. **A partial honest answer, never a fabricated complete one.** |
| No new evidence for 2 consecutive steps | Stop. Further searching is churn |
| Model returns malformed JSON | One repair retry; then default to `sufficient: true` with the evidence held so far. A degraded answer beats an infinite loop |
| Chosen action fails at A2 | A3 is re-invoked with the failure recorded; it must choose a different action |

## Tests
- A single-lookup question returns `sufficient: true` at step 1.
- A 3-hop question does not return `sufficient` before step 2.
- After a step yielding zero new chunks twice, the loop stops.
- Budget exhaustion produces `partial: true` with non-empty `missing[]`.
- `next_query` on a multi-hop question contains a term that first appeared in the
  previous step's results. **This is the test that proves the loop reasons rather
  than rephrases.**
