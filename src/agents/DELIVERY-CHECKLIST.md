# Acceptance and delivery checklist

This checklist distinguishes code that exists from behavior demonstrated against the
real archive. Fixture output must not be used as competition answer evidence.

## Live acceptance sequence

1. Start P1's corpus-backed API and confirm `/v1/ready` is ready with a nonempty index.
2. Search for Greyfell Citadel's recorded garrison; verify the correct plate and 3,695.
3. Start the chat service using the configured shared LLM client (README run command).
4. Run `python -m tests.reasoning.acceptance --preflight-only`, then `--suite dev`
   and `--suite unanswerable`. Preserve the output directories.
5. Read every saved answer and source excerpt. Enter correctness 0–3 in
   `human-review.csv` using the project's evaluation rubric; do not derive a judgment
   from lexical matching. Record refusal judgments as `true` or `false` where applicable.
6. Run `python -m tests.reasoning.review_report RUN_DIRECTORY`. A completed review
   means every executed question was judged; it does not mean every answer passed.
7. Record failures with qid, trace ID, expected behavior, observed evidence, and owner.
   Repeat affected cases after fixes and preserve both runs.

## Required demonstration evidence

| Case | Check | Evidence to preserve |
|---|---|---|
| Greyfell | 3,695 from its own plate; never Ironfell's value | Answer, citation, rendered figure |
| Emberdeep | 1,114; reference bars are not the answer | Labeled figure and cited claim |
| Thrice-Bound Edge | 94, with plate/wiki disagreement visible | Conflict resolution and both sources |
| Edge versus Lantern | Correct entity and labeled value | Source asset IDs and excerpts |
| Three-hop question | Later query uses newly discovered evidence | Actual A2/A3 trajectory |
| Unanswerable | Concrete missing information, no corroborated inventions | Packet and trace |
| Archive orders | Instructions quoted as data; warning visible | Retrieved span and packet warning |
| Misspelled name | Vocabulary-backed visible correction, working rollback | Original and rollback requests |

## Browser checks

- Submit a real question and observe the trace while the job is running.
- Verify the figure loads beside its claim and matches the cited asset.
- Check table layout, long excerpts, narrow viewport, and keyboard access.
- Inspect citations and verify source text remains literal, including HTML-like strings.
- Export an answer and confirm its packet and trace correspond to the displayed result.
- Exercise network failure and confirm the UI exits waiting with a useful message.

## Report and video assembly

- Describe the explicit A1–A6 state machine, frozen seam, ownership, and budgets.
- Include measured results with run IDs, reviewed question counts, failures, and limitations.
- Use an actual multi-hop trace for the trajectory diagram, preserving source identities.
- Explain authority tiers, figure label binding, name safeguards, and injection boundaries.
- Include reproducible service/evaluation commands, dependency lockfile, and setup requirements.
- Preserve original AI collaboration transcripts and real Git history; never reconstruct them.
- Record the above real demo cases, inspect the resulting video, then upload and verify playback.
- Obtain P1 cross-review and merge without squashing before final packaging.

Code freeze is listed as 9 September at 12:00. The handbook says submission at 20:00;
CLAUDE.md says 23:30. Confirm the official submission time before scheduling delivery.
