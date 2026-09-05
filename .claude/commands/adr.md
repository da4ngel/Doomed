---
description: Scaffold an Architecture Decision Record with the rationale left for the human
argument-hint: <short decision title>
allowed-tools: Read, Write, Glob
---

Create the next numbered ADR in `docs/adr/` for: **$ARGUMENTS**

1. Glob `docs/adr/ADR-*.md` to find the highest existing number; use the next one.
2. Write the file using the template below.
3. Fill `Context`, `Options considered` and `Consequences` from what you can see in
   the repo and this conversation.
4. **Leave the three human blocks as literal TODO markers. Do not write them.**
   Human-AI collaboration is 15% of the score and is assessed from these documents.
   Generated rationale reads as one-shot generation, which the rubric penalises.
5. Print the path and list exactly which sections the human still has to fill.

```markdown
# ADR-NNN: <title>

- Date: <today>
- Status: proposed
- Deciders: <names>

## Context
<what forced this decision — constraints, corpus facts, deadline pressure>

## Options considered
| Option | Pros | Cons | Cost to build |
|---|---|---|---|

## What the AI proposed
<!-- TODO human: what did Claude actually suggest first? -->

## What we rejected and why
<!-- TODO human: name the option you killed and the reason. At least three ADRs
     in this repo must record the team overruling the AI. -->

## Decision
<!-- TODO human -->

## Consequences
<what this makes easy, what it makes hard, what it forecloses>

## How we would know we were wrong
<the measurement that would falsify this decision>
```
