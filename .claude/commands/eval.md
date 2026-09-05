---
description: Run an evaluation suite and diff the result against the committed baseline
argument-hint: [suite name, or "all"] [--ablation]
allowed-tools: Bash, Read, Write
---

Run the evaluation for: **$ARGUMENTS** (default suite: `smoke`)

1. `make eval SUITE=$ARGUMENTS` — or with `--ablation`, run all nine configs.
2. Load `eval/baseline.json` and produce a delta table:

   | Metric | Baseline | Now | Delta |
   |---|---|---|---|

   Include at minimum: `recall@10`, `coverage@10`, `nDCG@10`, `groundedness`,
   `citation_precision`, `refusal_accuracy`, `p95_latency_ms`, `cost_per_query`.

3. Print the **failure taxonomy distribution** — `extraction` / `retrieval` /
   `synthesis` / `refusal`. This is the diagnosis, not the score. A drop in
   `synthesis` failures with flat `retrieval` failures means the prompt improved;
   the reverse means the index did.

4. List the five worst-scoring questions with their taxonomy label and one line on
   what went wrong.

5. If any metric moved more than 3 points in either direction, draft the
   `docs/decisions.md` entry recording it — date, what changed, the delta, and a
   TODO for the human to write why.

Do not update `eval/baseline.json` unless explicitly asked. The baseline moves by
human decision, never automatically.
