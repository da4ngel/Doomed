# Sample-questions evaluation — 28 questions, 9 September

Full end-to-end run of the reasoning layer (A1–A6, `POST /v1/chat`) against
`data/corpus/Ashen_Era_Archive/sample_questions.json` (20 dev questions) plus the
8 `eval/suites/unanswerable.json` questions. Every question's answer is recorded below with
a verdict, a rating, and — for every failure — the full reason and the verbatim error.

`sample_questions.json` ships **no gold answers**. Verdicts are graded against the
hand-authored gold in `eval/suites/{rich_1a,multihop_1b,contradiction_1c}.json` (quoted in
each entry) and cross-checked against `data/index/images.jsonl` for the figure questions.
This is the first answer-level measurement of the reasoning layer on the real dev set —
`docs/limitations.md` §1 ("the answer layer is unmeasured") is what this run addresses.

---

## Configuration

| | |
|---|---|
| Knowledge API (`:8000`) | 236 documents · 2,474 chunks · 2,474 vectors · 70 images described · 198 entities · 742 relations · `qdrant-server` · warm |
| Reasoning API (`:8001`) | `src.api.routes.chat:create_app`, restarted for this run |
| Synthesis / critic / verifier / analyst model | **`gpt-4o`** (OpenAI direct), confirmed from every packet's `usage[].model` |
| Vision | unchanged — the 70 figure descriptions are pre-computed and cached in `data/index/images.jsonl`, served via `/v1/assets/{id}/meta` |
| Budget per question | `budget=12` (Deep Semantic Search), `max_wall_ms=90_000`, `max_tokens_per_query=200_000` |
| Git commit | `cc55205` |
| Tokens | 415,969 in / 15,642 out · **≈ $1.20** at gpt-4o pricing (usage records report `cost_usd=0` for the OpenAI-direct path; this is an estimate) |
| Wall time | 12.3 min for 28 questions, 1 LLM-cache hit / 108 calls |

### Run integrity note — 11 questions were re-run

OpenAI's API began force-closing connections (`WinError 10054`, repeated) at question 17
of the first pass. Because `gpt-4o` is a bare model id it is pinned to OpenAI-direct with
**no provider fallback**, so every question after the drop burned the full 90 s wall
budget and returned nothing. Those 11 (`1b_009`, `1b_003`, both `1c_*`, `un_001`–`un_007`)
were re-run after OpenAI recovered; results below are the re-run. Two of the eleven
(`1b_003`, `un_007`) still hit the 90 s ceiling on the re-run — that is **genuine loop
churn**, reproduced across both passes, not infrastructure (their traces show 5–6 A2/A3
iterations finding nothing new). This fragility is itself finding #4 below.

---

## Rubric

**Correctness 0–3** (from `docs/evaluation.md` §2): 3 = matches gold and is correctly
grounded; 2 = substantially correct with a real defect (right answer but mis-labelled
support, or a missing conflict disclosure); 1 = partial / hedged / wrong process, right
outcome; 0 = wrong, fabricated, or nothing.

**PASS** = correctness ≥ 2 and the answer was actually delivered. **FAIL** otherwise.

**Rating /100** per question = correctness vs gold **55** + groundedness & citation
correctness **20** + track rigour **15** (1A: right value bound to the named subject +
figure attached; 1B: full hop-chain resolved and the question's own constraint respected;
1C: both competing claims surfaced + tier resolution shown) + latency/robustness **10**.

**Failure taxonomy** (`eval/taxonomy.py`): `extraction` (fact never left the document) ·
`retrieval` (gold chunk not in context) · `synthesis` (gold chunk present, answer wrong) ·
`refusal` (refused answerable / answered unanswerable).

---

## Scoreboard

| qid | track | verdict | correct 0–3 | /100 | grounded | cited docs vs gold | iters | wall s | taxonomy |
|---|---|
---|---|---|---|---|---|---|---|
| 1a_001 | 1A fig | ✅ PASS | 3 | 90 | 1.00 | plate ✓ | 1 | 2.7 | — |
| 1a_004 | 1A fig | ✅ PASS | 3 | 82 | 1.00 | plate ✓ | 9 | 36.4 | — (churn) |
| 1a_007 | 1A fig | ✅ PASS | 3 | 95 | 1.00 | plate ✓ | 1 | 2.0 | — |
| 1a_008 | 1A fig | ✅ PASS | 3 | 95 | 1.00 | plate ✓ | 1 | 2.4 | — |
| 1a_009 | 1A fig | ✅ PASS | 3 | 95 | 1.00 | plate ✓ | 1 | 0.1¹ | — |
| 1a_013 | 1A fig | ✅ PASS | 3 | 95 | 1.00 | plate ✓ | 1 | 2.8 | — |
| 1a_v06 | 1A portrait | ✅ PASS | 3 | 92 | 1.00 | portrait ✓ | 1 | 5.9 | — |
| 1a_v21 | 1A relic | ✅ PASS | 3 | 92 | 1.00 | illustration ✓ | 1 | 8.0 | — |
| 1a_v12 | 1A heraldry | ⚠️ borderline | 2 | 60 | 0.00 | heraldry ✓ | 1 | 8.8 | synthesis (A6) |
| 1a_v11 | 1A heraldry | ❌ FAIL | 0 | 15 | 0.00 | none | 1 | 6.3 | synthesis (A5) |
| 1a_v07 | 1A portrait | ❌ FAIL | 0 | 15 | 0.00 | none | 1 | 5.9 | synthesis (A5) |
| 1b_005 | 1B | ✅ PASS | 3 | 88 | 1.00 | 1/3 gold | 2 | 43.3 | — |
| 1b_006 | 1B | ✅ PASS | 3 | 80 | 1.00 | 1/2 gold | 1 | 17.5 | — |
| 1b_022 | 1B | ✅ PASS | 3 | 85 | 1.00 | 0/3 gold² | 3 | 65.8 | — |
| 1b_009 | 1B | ⚠️ borderline | 2 | 55 | 0.00 | 0/2 gold² | 5 | 33.7 | synthesis (A6) |
| 1b_007 | 1B | ❌ FAIL | 0 | 20 | 0.00 | none | 2 | 30.5 | synthesis (A6) |
| 1b_013 | 1B | ❌ FAIL | 0 | 25 | 1.00 | 0/2 gold | 2 | 44.5 | synthesis (A5) |
| 1b_003 | 1B | ❌ FAIL | 0 | 8 | 0.00 | none | 5 | 90.1 | retrieval + budget |
| 1c_003 | 1C | ⚠️ weak PASS | 2 | 65 | 1.00 | codex ✓ | 2 | 20.0 | — (no conflict shown) |
| 1c_000 | 1C | ❌ FAIL | 0 | 10 | 1.00³ | 0/1 gold | 2 | 9.7 | retrieval + synthesis |
| un_001 | unans | ✅ PASS | 2 | 78 | n/a | — | 1 | 16.9 | — |
| un_002 | unans | ⚠️ borderline | 1 | 55 | n/a | — | 3 | 30.9 | refusal (over-refused) |
| un_003 | unans | ✅ PASS | 3 | 85 | n/a | — | 3 | 35.7 | — |
| un_004 | unans | ✅ PASS | 3 | 88 | n/a | — | 1 | 19.2 | — |
| un_005 | unans | ❌ FAIL | 1 | 45 | 1.00 | — | 1 | 10.2 | refusal (answered un-established) |
| un_006 | unans | ✅ PASS | 3 | 85 | n/a | — | 3 | 37.0 | — |
| un_007 | unans | ⚠️ borderline | 1 | 40 | n/a | — | 6 | 90.1 | refusal via budget |
| un_008 | unans | ❌ FAIL | 1 | 35 | 1.00 | — | 4 | 60.0 | refusal (non-sequitur) |

¹ served from the LLM cache (identical prompt from a prior session). ² answer verified
against `the_annals_of_the_ashen_era` (tier 1), which is a valid corroborating source not
listed in the hand gold — scored as grounded-correct. ³ grounded, but to the **wrong-tier**
value.

### Aggregates

| group | n | clean PASS | borderline | FAIL | mean correctness | mean /100 | mean groundedness |
|---|---|---|---|---|---|---|---|
| **1A figure plates** | 6 | 6 | 0 | 0 | **3.00** | **92** | 1.00 |
| **1A portrait / heraldry / relic** | 5 | 2 | 1 | 2 | 1.60 | 55 | 0.60 |
| **1B multi-hop** | 7 | 3 | 1 | 3 | 1.57 | 53 | 0.71 |
| **1C contradiction** | 2 | 0 | 1 | 1 | 1.00 | 38 | 1.00 |
| **20 dev questions** | 20 | 11 | 3 | 6 | **1.95** | **62** | **0.75** |
| **Unanswerable** | 8 | 4 | 2 | 2 | 2.13 | 64 | n/a |

- **Lexical answer match** (diagnostic only): 14/20 dev questions. This *over*-counts (it
  passes `1a_v12` and `1b_009`, which are marked "not verified") and *under*-counts nothing.
- **`refusal_accuracy`** (unanswerable answered without asserting the missing fact): **6/8**
  (`un_005` asserted an appearance the corpus text declines to establish; `un_008` answered
  with an unrelated fact and flagged no gap).
- **`false_refusal_rate`** (answerable questions returned with no answer): **4/20 = 0.20**
  (`1a_v11`, `1a_v07`, `1b_007`, `1b_003`).
- **Partial-packet rate**: 12/20 dev — but ~4 of those are *spurious* (the composer echoes
  the question back into `missing_information` even on a correct, verified answer: `1a_001`,
  `1a_004`).
- **Confidence display bug persists**: 9 correct, verified answers show `confidence: 0.0`
  because the composer copies the `0.0` placeholder from its own prompt schema
  (`docs/reports/acceptance-2026-09-07.md` §"Every answer reports 0% confidence").

### Headline

**Figure-plate 1A is production-grade — 6/6, every trap resisted** (the Emberdeep 1,114
trap, the gauge "largest = 10" trap, the Edge/Lantern name collision, the "all reference
bars exceed the answer" trap). Since `docs/corpus-findings.md` estimates 1A is over half
the hidden set, this is the right thing to be strong at.

**Everything that needs more than one lookup is fragile.** Multi-hop composition
(`1b_007`, `1b_013`), tier-based contradiction resolution (`1c_000` returns the *tier-4*
year), portrait/heraldry claim-binding (`1a_v07`, `1a_v11` compose nothing from a correctly
retrieved image), and the A6 verifier being strict enough to delete correct answers
(`1a_v12`, `1b_009`, `1b_007`).

**Run-level rating: ~62/100** on the 20 dev questions.

---

## Per-question detail

Legend: **G** = gold answer · **A** = system `answer_markdown` (verbatim) · then the
verdict, what went well, what to improve, and (for failures) the full reason + error.

---

### 1A — figure plates (6/6 PASS)

#### `1a_001` — Emberdeep garrison strength ✅ PASS · 3/3 · 90/100
- **Q:** According to the figure plate illustrating Emberdeep's forces, what is the recorded total of its garrison strength?
- **G:** `1,114` (the planted trap — 800 / 2,400 / 6,000 are reference bars; Tesseract reads 1,114 as "Ee"; the 1,114 bar is drawn *shorter* than the 6,000 bar).
- **A:** `Emberdeep: 1,114` + `[cite]` + `[FIG:img_29ea682914218630]`
- **Verdict:** Correct, bound to the named subject, figure attached, cited to the tier-1 plate. A3: *"the recorded total of Emberdeep's garrison strength is 1,114 soldiers"*. This is the single clearest justification for ADR-002 (vision over OCR) in the corpus and the system nails it in one iteration, 2.7 s.
- **Went well:** Label→value binding defeats all three distractors. `numeric_figure_draft` deterministic path fires.
- **Could be better:** `partial: true` and `missing_information` echoes the question verbatim — a rendering bug (`src/agents/composer.py` re-adds the sub-question to `missing_information` when the deterministic draft is used). A judge reading the packet sees a correct answer flagged "unresolved". `confidence: 0.6`.
- **How:** in `AnswerComposer.compose`, don't carry `state.critique.missing` into `missing_information` when every sub-question is answered by an accepted claim.

#### `1a_009` — Greyfell Citadel garrison ✅ PASS · 3/3 · 95/100
- **Q:** According to the figure plate, what is the recorded garrison strength of Greyfell Citadel?
- **G:** `3,695` (control case — no trap; image-only, appears in no document).
- **A:** `Greyfell Citadel: 3,695` + `[cite]` + `[FIG]`
- **Verdict:** Correct, clean, non-partial, grounded to the tier-1 plate. Served from the LLM cache (0.1 s) — the prompt was identical to a prior session, which is legitimate cache behaviour.
- **Could be better:** nothing of substance. `confidence` renders `0.9` here (the deterministic path sets it), unlike the portrait answers.

#### `1a_007` — Thrice-Bound Lantern attunement cost ✅ PASS · 3/3 · 95/100
- **G:** `55`. Two stacked traps: (1) one-token name collision with "Thrice-Bound Edge" (94); (2) `55` is also this plate's own "Adept tolerance" reference bar.
- **A:** `The Thrice-Bound Lantern: 55` + `[cite]` + `[FIG]`
- **Verdict:** Correct plate retrieved (BM25 on the rare proper noun beats the collision), correct value bound to the subject and not to the identically-valued reference bar. 2.0 s, one iteration.

#### `1a_004` — Thrice-Bound Edge "shards of will" ✅ PASS · 3/3 · 82/100
- **G:** `94`. A contradiction trap: `wiki/the_thrice_bound_edge.md` asserts "no attunement cost" six times and ranks first on dense retrieval; only the tier-1 plate carries 94.
- **A:** `The Thrice-Bound Edge: 94` + `[cite]` + `[FIG]` — with `Still unresolved: How many shards of will are required…`
- **Verdict:** Right answer, tier-1 plate, resisted the wiki "none recorded" contradiction. **But it took 9 iterations / 36 s**: the plate labels the value in *vitae-grains*, the question says *shards of will*, and A3 churned five extra retrieval rounds hunting for "shards of will" as a distinct concept (trace steps 4–19, all `newgold=0` on the actual number). It correctly did **not** blindly map the unit — that is the composer instruction "do not map an unknown unit onto a familiar unit" working — but it also never told the reader "the plate measures this in vitae-grains; the question's 'shards of will' is the same quantity".
- **Could be better:** the A3 sufficiency critic should accept "the named subject's value is present" and stop, rather than requiring the question's exact noun phrase to appear in evidence. The spurious `partial`/`missing_information` again.
- **How:** `src/agents/critic.py` `_validate` — a numeric figure claim whose value matches the requested subject label should satisfy coverage even when the question's unit word is absent.

#### `1a_013` — Cinder-Wrought Aegis attunement cost ✅ PASS · 3/3 · 95/100
- **G:** `34`. Trap: all three reference bars (20/55/85) exceed the answer, so "largest number" and "longest bar" both fail.
- **A:** `The Cinder-Wrought Aegis: 34` + `[cite]` + `[FIG]` — 2.8 s, one iteration, non-partial.
- **Verdict:** Correct, clean.

#### `1a_008` — Weeping Lurker threat rating ✅ PASS · 3/3 · 95/100
- **G:** `3`. Trap: a gauge (not a bar chart); axis endpoints 0 and 10 are text, caption says "of 10".
- **A:** `Weeping Lurker: 3` + `[cite]` + `[FIG]` — 2.4 s.
- **Verdict:** Correct; the chart-grammar generalisation (gauge, not just bar chart) holds.

---

### 1A — portrait / heraldry / relic illustrations (2 PASS, 1 borderline, 2 FAIL)

#### `1a_v06` — Ignatz Ashgrove's held object ✅ PASS · 3/3 · 92/100
- **G:** `a rolled scroll` (atmo portrait, **zero OCR characters** — vision-only).
- **A:** `In the portrait of Ignatz Ashgrove the Oathless, they are holding a rolled scroll.` + `[cite]` + `[FIG]`
- **Verdict:** Correct, grounded (`single_source`), figure attached. The `_portrait_quotes` caption-expansion in `src/agents/composer.py` worked — the claim binds to the portrait whose description reads "clutching a sealed parchment scroll".
- **Could be better:** `confidence: 0.0` display bug.

#### `1a_v21` — Gauntlet of Sorrowfell engraved motif ✅ PASS · 3/3 · 92/100
- **G:** `a serpent`. Trap: skulls decorate the border on all four sides; the serpent is on the gauntlet itself.
- **A:** `The motif engraved on the Gauntlet of Sorrowfell in its official illustration is a coiled serpent.` + `[cite]` + `[FIG]`
- **Verdict:** Correct, distinguishes the engraved motif from the border ornament, grounded, figure attached.
- **Could be better:** `confidence: 0.0`.

#### `1a_v12` — House Morvain banner emblem ⚠️ BORDERLINE · 2/3 · 60/100
- **G:** `two crossed keys`. Trap: skulls on the finials and crest; the emblem is on the shield.
- **A:** `Inference (not verified): The central emblem on the banner of House Morvain is two crossed skeleton keys.` + `[cite]` + `[FIG]` + `Still unresolved: One or more requested facts could not be verified against their cited evidence.`
- **Verdict:** The **content is correct** ("two crossed skeleton keys" — `images.jsonl` `objects_depicted` confirms "two crossed skeleton keys with trefoil bow ends"), the right figure is attached, and it correctly avoids the skull distractor. **But A6 downgraded the claim to `support: "inferred"`**, so `groundedness = 0.00`, `partial: true`, and the answer is prefixed "Inference (not verified)" — to a judge this reads as an unreliable guess.
- **Full reason:** `A6 verify → 1 downgraded`. The cited excerpt is the figure description *"Subject: Heraldic banner displaying a black and white shield with two crossed keys on an ornate gold escutcheon"*. gpt-4o's entailment call (`src/agents/verifier.py` `_entailment`) judged that this excerpt does **not entail** "the central emblem on the banner of House Morvain is two crossed skeleton keys" — plausibly because the excerpt says "keys" not "skeleton keys", and does not use the phrase "central emblem". The verifier is being literal about phrasing rather than semantic about content.
- **How:** the entailment prompt says "Mere topical similarity is not entailment" and "distinguish the exact subject". For figure-description evidence, a looser standard is appropriate — the description *is* the ground truth for the image. Options: (a) route figure/portrait claims through a vision re-check instead of text entailment; (b) in `_entailment`, treat a claim as entailed when its head noun phrase (`crossed keys`) is a substring of the excerpt and the subject entity matches; (c) have A5 copy the description's own wording ("crossed keys") rather than embellishing ("skeleton keys").

#### `1a_v11` — Ashen Vanguard banner emblem ❌ FAIL · 0/3 · 15/100
- **G:** `a weeping eye`. Trap: the eye sits inside a radiant star; a skull tops the pole.
- **A:** `I could not establish an answer from the retrieved evidence. Still unresolved: No proposed claim had valid supporting evidence…`
- **Verdict:** FAIL. The evidence was retrieved and A3 read it correctly — trace step 3: *"the banner depicting a large open eye surrounded by a spiked halo and weeping golden tears"*. Then **A5 composed zero claims**.
- **Full reason + error:** `warnings: [claim_downgraded / removed / "Visual question requires a supporting figure"]`. In `src/agents/composer.py` `_accept_draft`: `if requires_visual and not proposed.asset_ids and not _is_table(...)` → the claim is dropped. gpt-4o proposed a text claim for a visual question **without attaching an `asset_id`**, so the guard removed it and there was nothing left. Taxonomy: `synthesis`. Note the same model *did* attach the asset for `1a_v06` and `1a_v21` — the binding is non-deterministic.
- **How:** when `requires_visual` and the draft claim has no `asset_ids` but exactly one figure is in the evidence bundle and its description supports the claim, attach it automatically rather than deleting the claim. Or make the A5 prompt hard-require `asset_ids` on any claim for a `requires_visual` question and re-prompt once if missing.

#### `1a_v07` — Aldous Wrenfield's held object ❌ FAIL · 0/3 · 15/100
- **G:** `a chalice`. Trap: a sword hilt and a banner are also in frame; the chalice is the object *held up*.
- **A:** `I could not establish an answer from the retrieved evidence. Still unresolved: No proposed claim had valid supporting evidence…`
- **Verdict:** FAIL, identical mechanism to `1a_v11`. A3 step 3: *"Aldous Wrenfield is depicted holding an ornate golden chalice"* — read correctly. A5 composed 0; `claim_downgraded / removed / "Visual question requires a supporting figure"`. Taxonomy: `synthesis`.
- **How:** same as `1a_v11`.

---

### 1B — multi-hop (3 PASS, 1 borderline, 3 FAIL)

#### `1b_005` — Isolde Mournvale's faction's war ✅ PASS · 3/3 · 88/100
- **G:** `The War of Drowned Light`. Chain: Isolde Mournvale → member_of → The Silent Choir → won → The War of Drowned Light.
- **A:** `The war won by the organization that included Isolde Mournvale as one of its members was The War of Drowned Light.` + 3 citations (`the_annals_of_the_ashen_era` ×2, `isolde_mournvale`).
- **Verdict:** Correct, both hops resolved (trace steps 3 and 5), `support: "corroborated"`, grounded. Cites the Annals (tier 1) plus the member article. 43 s, 2 iterations.
- **Could be better:** cites the Annals rather than `the_war_of_drowned_light` / `the_silent_choir` (the hand-gold docs) — the Annals is a legitimate tier-1 corroboration, so this is fine, but `citation_recall` against the literal gold set is 1/3.

#### `1b_022` — Ravena Stormwell's faction's war ✅ PASS · 3/3 · 85/100
- **G:** `The War of Drowned Light`.
- **A:** `Ravena Stormwell's faction, The Silent Choir, was the victor of The War of Drowned Light.` + `[cite the_annals_of_the_ashen_era]`
- **Verdict:** Correct, both hops in the trace, grounded (`single_source`, the Annals). 66 s / 3 iterations — slow but correct.
- **Could be better:** single citation to the Annals; no cross-check against `ravena_stormwell.md`. `confidence: 0.0`.

#### `1b_006` — a member of the War of Drowned Light victor ✅ PASS · 3/3 · 80/100
- **G:** any member of The Silent Choir (`accept`: Ignatz Fellgard, Brannoc Palefroth, …).
- **A:** `One of the individuals who was a member of the faction that won the War of Drowned Light is Ignatz Fellgard.` + 2 citations (`the_silent_choir` members row). `Still unresolved: What factions were involved in the War of Drowned Light?`
- **Verdict:** Correct — "Ignatz Fellgard" is on the accept list; grounded to the Silent Choir members row. 1 iteration, 17 s.
- **Could be better:** awkward hedged phrasing ("One of the individuals…"); spurious `missing_information` about factions that aren't part of the question. `confidence: 0.0`.

#### `1b_009` — Halvard Crowhurst ↔ Purge of Blackport victors ⚠️ BORDERLINE · 2/3 · 55/100
- **G:** "he is a member of The Iron-Ring Cartel, which won the Purge of Blackport" (`accept`: "member of The Iron-Ring Cartel").
- **A:** `Inference (not verified): Halvard Crowhurst is connected to the victors of the Purge of Blackport as a member of The Iron-Ring Cartel.` + `[cite the_annals_of_the_ashen_era]` + 3 "still unresolved" lines.
- **Verdict:** **Content correct** and the hard part worked — Halvard has no wiki article and is reachable only through the Annals registry, which the system found (trace step 5). **But A6 downgraded to `inferred`** → groundedness 0, partial. 5 iterations, 34 s.
- **Full reason:** `A6 verify → 1 downgraded`; cited excerpt *"The surviving registry identifies Halvard Crowhurst as a member of The Iron-Ring Cartel…"*. gpt-4o entailment apparently rejected the link to "victors of the Purge of Blackport" because that half of the claim is a separate fact (the Cartel won the Purge) carried by a different chunk that was not among this claim's citations.
- **How:** A5 should attach **one citation per hop** to a multi-hop claim (the members-row chunk *and* the "Iron-Ring Cartel won the Purge" chunk). The composer instruction asks for "exact source quotes that entail it" but does not say "one per link in the chain". Add that, and A6's per-citation check will pass.

#### `1b_007` — Ederon Fellgard's faction's accord ❌ FAIL · 0/3 · 20/100
- **G:** `The Leaden Accord`. Trap: the Iron-Ring Cartel won **two** events (The Winter Reckoning and The Leaden Accord); "accord" in the question is the disambiguator.
- **A:** `I could not establish an answer from the retrieved evidence. Still unresolved: What role did Ederon Fellgard play in the accord?`
- **Verdict:** FAIL — and the answer was **found and then thrown away**. Trace step 5: *"Ederon Fellgard is confirmed as a member of the Iron-Ring Cartel, which won the Leaden Accord"*. A5 composed a claim (step 7: `compose found=1`), then **A6 removed it** (step 8: `verify → 1 removed`).
- **Full reason + error:** `warnings: [claim_downgraded / removed / "claim_1"]` — in `src/agents/verifier.py`, a claim with `verdict == "contradicted"` **or no surviving citations** is deleted. Either gpt-4o's entailment returned `contradicted`/`unsupported`, or A6's `_citations` check dropped the claim's citation (excerpt not byte-verbatim in the source chunk). Taxonomy: `synthesis` (evidence present, verification failed). This is the exact pattern `docs/reports/acceptance-2026-09-07.md` §4 flagged: *"A5 composes a multi-hop claim and its cited excerpts do not support it."*
- **How:** (1) per-hop citations as above; (2) log the A6 entailment verdict and the dropped-citation reason into the trace so "removed" is diagnosable without re-running; (3) consider a "downgrade, don't delete" policy for multi-hop claims whose *last* hop is entailed — surface it as `inferred` with the chain shown, rather than returning nothing.

#### `1b_013` — dominion over the Gravemaw Wyrm's lair ❌ FAIL · 0/3 · 25/100
- **G:** `The Bleeding Crown`. Chain: Gravemaw Wyrm → lair_of → Marrowwell Abbey → ruled_by → The Bleeding Crown.
- **A:** `The lair of the Gravemaw Wyrm is in Marrowwell Abbey.` + `[cite codex_vaeloria_ii]`
- **Verdict:** FAIL — **stopped one hop short**. The question asks *whose dominion*; the answer gives the *place*. And the system **had the second hop**: trace step 5: *"The Bleeding Crown governing Marrowwell Abbey addressed the question of dominion over the lair"*. A5 then composed only the first-hop fact. Grounded and verified — but to the wrong question. Taxonomy: `synthesis`.
- **How:** A5's prompt needs to check the composed claim against the question's actual interrogative ("whose" → the answer must be an agent/organisation, not a place). A cheap guard: if `analysis.intent == "multi_hop"` and the final claim's answer type doesn't match the wh-word, re-prompt with "the question asks for X, your answer names Y".

#### `1b_003` — the shadowed redoubt housing Cerys Sablewood's relic ❌ FAIL · 0/3 · 8/100
- **G:** `Gloamreach`. Chain: Cerys Sablewood → bore_since (356 AS) → The Cinder-Wrought Aegis → housed_at → Gloamreach. Hop 2 is prose-only (the Aegis article has no infobox).
- **A:** `Sources disagree about The Cinder-Wrought Aegis forging year: 342 AS (tier 1) versus 354 AS (tier 4)…` then `I could not establish an answer… Investigation stopped: LLM deadline exceeded`.
- **Verdict:** FAIL — worst result in the run. The oblique phrasing ("shadowed redoubt", the relic named only via "borne by Cerys Sablewood since 356 AS") gave the analyst little to seed on. The loop churned 5 iterations (trace steps 2–11, all `newgold` small and irrelevant), **hallucinated a conflict about the Aegis *forging year*** (342 vs 354 — neither is even the gold value, and forging year is not what the question asks), decomposed into 8 sub-questions, and hit the 90 s wall during composition.
- **Full reason + error:** `warnings: [tool_failure/composition_failed/BudgetExceeded, tool_failure/critic_degraded/"Coverage could not be validated", asset_unresolved ×3 /BudgetExceeded, budget_exhausted/"LLM deadline exceeded; in-flight usage unknown"]`. Reproduced at 90.1 s on both the first pass and the re-run. Taxonomy: `retrieval` (the `housed_at → Gloamreach` prose was never surfaced) compounded by `budget`.
- **How:** this is `docs/limitations.md` §12 (oblique 1B) made concrete. Levers: (a) LLM-extracted `housed_at`/`located_in` edges over the infobox-less articles so the graph can do the second hop; (b) a churn guard — after 2 iterations with no gold-relevant gain, stop and return "partial: could resolve hop 1 (the Cinder-Wrought Aegis) but not hop 2"; (c) suppress `ConflictAdapter` output when the conflicting attribute (`forging year`) is not mentioned in the question.

---

### 1C — contradiction (1 weak PASS, 1 FAIL)

#### `1c_003` — year the Gauntlet of Sorrowfell was forged ⚠️ WEAK PASS · 2/3 · 65/100
- **G:** `391 AS` (tier-1 codex). Competing: `360 AS` (tier-5 sermon). Trap: "Psalter of Seven Sorrows" forged 119 AS matches on "Sorrow".
- **A:** `The year the 'Gauntlet of Sorrowfell' was actually forged is 391 AS.` + 2 citations to `codex_vaeloria_ii` ("forged: 391 AS").
- **Verdict:** **Right answer, right source** (tier-1 codex), avoided the Psalter decoy. **But `conflicts: []`** — the packet never surfaces the competing `360 AS` claim or shows the tier resolution. A3 *saw* the disagreement (step 3: *"other sources dispute this"*; step 5: *"conflicting information regarding the forging date"*) but nothing reached `packet.conflicts`. The 1C track requirement (`docs/corpus-findings.md` Finding 4, `eval/suites/contradiction_1c.json`) is explicitly "find the competing claims and resolve them by authority tier" and "surfacing the disagreement is a feature". The answer is correct; the *demonstration* of the contradiction machinery is absent.
- **How:** the `ConflictAdapter` (`src/agents/conflict_adapter.py`) only emits a `Conflict` when `detect_conflicts` (pattern-based, `src/synthesis/conflicts.py`) matches both values in the merged chunks. Here the tier-5 sermon's "360 AS" was likely not in the final bundle after `focused_chunks`/`merge_evidence` narrowing. Either widen what the conflict detector sees (run it on the pre-focus chunk set) or have A5, when A3's reasoning mentions a disagreement, explicitly retrieve the competing value and emit the `Conflict`.

#### `1c_000` — true founding year of Gloamreach ❌ FAIL · 0/3 · 10/100
- **G:** `246 AS` — **tier-1** `codex_vaeloria_i_gazetteer_of_the_sundered_realms` ("Gloamreach's founded is 246 AS"). Competing: `286 AS` (tier 4), `295 AS` (tier 4). Trap: `wiki/gloamreach.md` gives no year ("Contested; consult the Annals and Codex").
- **A:** `Gloamreach was founded in 286 AS.` + 2 citations to **tier-4** contracts (`contract_concerning_thessaly_coldwater`, `contract_concerning_the_sceptre_of_final_winter`).
- **Verdict:** FAIL — **confidently wrong, with the wrong-tier value and a real citation**. This is precisely the failure mode `README.md` and `docs/limitations.md` say the corpus punishes hardest. The system found two tier-4 contracts that agree on 286, marked the claim `corroborated`, and never retrieved the tier-1 codex that says 246. A3 step 3: *"The true founding year of Gloamreach is stated as 286 AS in multiple sources. Despite other sources' disputes, this specific year is clearly [authoritative]"* — the reasoning inverts the tier rule (treats "two agreeing tier-4 primary records" as outranking a tier-1 reference).
- **Full reason:** taxonomy `retrieval` + `synthesis`. Retrieval: `codex_vaeloria_i` was never in context — only 2 `hybrid_search` calls fired for a `contradiction`-intent question, and graph expansion (which `tune_for_intent` enables for `contradiction`) did not surface the codex chunk (the codex may not be graph-linked to the `Gloamreach` entity). Synthesis: even on tier-4-only evidence, the composer should have flagged the known disagreement rather than asserting `corroborated`.
- **Regression note:** `docs/reports/acceptance-2026-09-07.md` (run 3, `gpt-4o-mini`) resolved this one **correctly** — *"Gloamreach was founded in 246 AS … 246 AS (tier 1) versus 286 AS (tier 4). Tier 1 outranks tier 4."* This run (`gpt-4o`, budget 12, current retrieval policy) is worse on `1c_000`. Whether the cause is the model, the retrieval-policy change, or cache differences needs a controlled A/B — but a green retrieval gate did not catch it because the gate does not score answers.
- **How:** (1) for `contradiction` intent, force a minimum of one codex/tier-1-targeted retrieval pass (filter `authority_tier=[1]`) before composing; (2) A3 must not report `sufficient` on a contradiction question until it has evidence from **at least two tiers**; (3) A5's "prefer lower-numbered authority tiers on the SAME subject" rule needs the tier-1 evidence physically present to apply — it can't prefer what it never retrieved.

---

### Unanswerable suite (4 PASS, 2 borderline, 2 FAIL)

Graded on `eval/suites/unanswerable.json` `expected_behaviour`: non-empty
`missing_information` naming the gap; no `corroborated`/`single_source` claim asserting the
missing fact; ideally still cite the nearest related document.

#### `un_001` — how Aldous came to command Fenspire ✅ PASS · 2/3 · 78/100
- **A:** `I could not establish an answer… Still unresolved: specific circumstances under which Aldous Wrenfield came to command Fenspire`
- **Verdict:** Correct refusal. A3 step 3 nails the distinction: *"confirms Aldous has commanded Fenspire since 336 AS, but explicitly states the record does not establish [the circumstances]"* — it did **not** invent a reason from the `commands` edge. Names the gap.
- **Could be better:** no citation to `aldous_wrenfield_the_last_warden` (the "nearest related" the rubric wants, to show it looked). `claims: []` + `citations: []`.

#### `un_003` — when the Thessaly mentorship began ✅ PASS · 3/3 · 85/100
- **A:** refuses, names both sub-gaps ("when… began", "what… involved"). Did not invent a date from the `mentor_of` edge. Good.

#### `un_004` — recipients of the sold intelligence ✅ PASS · 3/3 · 88/100
- **A:** `I could not establish… Still unresolved: Who were the recipients…`. A3: *"the record explicitly states that the recipients… are not specified"*. Clean, 1 iteration.

#### `un_006` — how long Caedmon served at Stormmarch ✅ PASS · 3/3 · 85/100
- **A:** refuses, names the gap ("Exact length of Caedmon Hollowmere's service"). Walked the graph (step 4: `graph_neighbors`), confirmed the `service` relation exists but has no duration, and did not fabricate one.

#### `un_002` — appearance/origin/powers of The Silent Psalter ⚠️ BORDERLINE · 1/3 · 55/100
- **Expected:** partial answer — the infobox gives appearance and origin; flag that powers are not recorded (`docs/reports/acceptance-2026-09-07.md` describes exactly this as the intended shape).
- **A:** `I could not establish an answer from the retrieved evidence.` — a **blanket refusal**.
- **Verdict:** Over-refusal. A3 step 7: *"All sub-questions… are directly answered with the provided quotes"* — then A5 composed 0. `warnings: [claim_downgraded / removed / "Visual question requires a supporting figure"]` — the question was routed as `visual` (the word "appearance"), and the same asset-binding failure as `1a_v07`/`1a_v11` deleted the claim. Safe (no fabrication) but not the graded-correct behaviour.
- **How:** the visual-question guard in `src/agents/composer.py` should not apply to questions that also ask non-visual sub-questions ("origin and powers"); and the portrait asset-binding fix (above) resolves this too.

#### `un_007` — reconciling Brannoc's death vs. his later wielding ⚠️ BORDERLINE · 1/3 · 40/100
- **Expected:** "the archive records both and reconciles neither" — explicitly *not* a tier resolution (resolving it "invents canon").
- **A:** `I could not establish an answer… Investigation stopped: LLM deadline exceeded` (90.1 s, both passes).
- **Verdict:** The *outcome* is safe (it did not invent a reconciliation, did not resolve by tier). But it got there by **timing out after 6 churning iterations**, not by reasoning "the canon states both and reconciles neither" — which A3 actually articulated at step 5 (*"the canon does not resolve the contradiction"*) and then kept searching instead of composing. A well-formed answer would state the two records and that canon offers no reconciliation.
- **How:** when A3's own `reason` contains an explicit "not established / not resolved / does not establish" finding, that **is** the answer for an unanswerable-shaped question — A5 should compose "the record establishes X and Y and does not reconcile them" and stop, rather than the loop continuing until the wall budget kills it.

#### `un_005` — what Maelis Harrowick looks like ❌ FAIL · 1/3 · 45/100
- **Expected (per suite):** unanswerable — "Maelis's appearance is not established beyond the epithet the Pale". Trap: articles describe *demeanour* at length while stating no canonical *appearance*.
- **A:** a full physical description — *"gaunt, pale figure with long dark hair… tattered black cloak fastened with a skull clasp… a white barn owl perched on their shoulder…"* — grounded to `atmo_portrait_character_maelis_harrowick_the_pale.png`, non-partial, `missing_information: []`.
- **Verdict:** Per the suite this is a **false-non-refusal**: the system asserted an appearance the corpus *text* declines to establish, by reading it off an atmo portrait. **Caveat:** the repo contradicts itself here — `docs/reports/acceptance-2026-09-07.md` explicitly calls `un_005` *"the one packet with no missing_information, and correctly so: it is fully answerable from the portrait plate"*. So this is either a correct vision-answer or a trap failure depending on whether the portrait counts as canonical. Scored 1 and flagged for the team to settle.
- **How:** decide the policy — does an `atmo_*` portrait establish "appearance" for an entity whose article says appearance is unrecorded? If no, the composer needs a rule that a portrait description cannot answer an "appearance" question when a text source explicitly disclaims it (the same conflict machinery, text-tier vs image).

#### `un_008` — what the Marrowwell Abbey vault guards ❌ FAIL · 1/3 · 35/100
- **Expected:** name the gap — the ledger lists possibilities ("coin, blood, a road, or nothing a sane clerk should name") and establishes nothing.
- **A:** `Marrowwell Abbey is identified as the lair of the Gravemaw Wyrm.` + `[cite codex_vaeloria_ii]` — non-partial, `missing_information: []`.
- **Verdict:** FAIL — a **non-sequitur presented as an answer**. It does not address what the vault guards (correct — that is not established) but instead of refusing or naming the gap, it states an unrelated fact and flags nothing. A3 step 7 even chased the trap: *"the garrison shall deny unauthorized access to the 'Sceptre,' indicating it may be what the vault is guarding"* — then didn't use it, which is good, but the final answer ignores the question entirely.
- **How:** A5 must check that the composed claim is *responsive* to the question. A claim about "the lair of the Gravemaw Wyrm" for a question about "what the vault guards" should trip a relevance guard → refuse and name the gap.

---

## Cross-cutting findings

### 1. Figure-plate 1A is a genuine, demonstrable strength — 6/6, every trap resisted
The Emberdeep planted trap (1,114 not 6,000), the gauge trap (3 not 10), the Edge/Lantern
name collision, the value-collision on plate 07 (55 is also a reference bar), and the
"all reference bars exceed the answer" grammar on plates 04 and 13 — all handled, in 1
iteration and ~2–3 s each, with the figure attached and a tier-1 citation. Given
`docs/corpus-profile.md` estimates 1A is >50% of the hidden set, this is the right
competency to have nailed. `numeric_figure_draft` (the deterministic extractive path) is
carrying this and it works.

### 2. A6 (verifier) deletes or downgrades correct answers — the single highest-value fix
`1a_v12` (keys), `1b_009` (Iron-Ring Cartel), `1b_007` (Leaden Accord) all had the
**correct content** and were killed or stamped "not verified" by A6's entailment step.
Two distinct causes:
- **Figure descriptions fail text-entailment** because the claim rephrases the description
  ("crossed keys" → "crossed skeleton keys") or adds framing ("central emblem"). The
  description *is* the ground truth for an image; text-entailment is the wrong test.
- **Multi-hop claims carry one citation for a two-fact statement**, so A6's per-citation
  check drops it. A5 needs to attach one citation per hop.

Impact: groundedness on the 20 dev questions is **0.75** where the correct-answer rate is
higher. Fixing A6/A5 binding would move ~3 borderline/fail questions to PASS and lift
groundedness toward 0.9 without touching retrieval.

### 3. The A5 composer under-answers and mis-routes
- **Stops a hop short** (`1b_013`: names the abbey, not its ruler — though it *found* the
  ruler).
- **Drops visual claims that lack an `asset_id`** (`1a_v07`, `1a_v11`, `un_002` — the model
  proposed the right claim, forgot to bind the figure, the guard deleted it). Non-deterministic:
  the same model bound the asset correctly on `1a_v06` and `1a_v21`.
- **Answers a different question than asked** (`un_008`).
- **Spurious `partial`/`missing_information`** on correct answers (`1a_001`, `1a_004`,
  `1b_006`) — echoes the sub-question back even when it's answered.

### 4. 1C contradiction handling does not demonstrate the contradiction machinery
Both 1C questions returned `conflicts: []`. `1c_003` got the right year but never showed
the competing claim; `1c_000` returned the **tier-4** year and called it `corroborated`.
The A4 conflict layer is described as "the 1C answer path, not a bonus"
(`docs/corpus-findings.md` Finding 4) and on this run it is invisible in the output. Root
causes: (a) contradiction-intent retrieval isn't reliably pulling tier-1 codex chunks;
(b) `detect_conflicts` runs on the post-focus bundle, which has already dropped the losing
value; (c) A3 marks a contradiction question "sufficient" on single-tier evidence.

### 5. No LLM-provider fallback — a demo-fragility risk
`gpt-4o` (bare id) pins to OpenAI-direct with no fallback (`src/agents/runtime.py`
provider-pinning rule). When OpenAI dropped connections mid-run, 11 questions failed hard
at the 90 s wall. For the demo/submission, use `openai/gpt-4o` via OpenRouter, or a model
id both providers share, so the fallback chain (`src/core/llm.py`) actually engages. The
budget code correctly caps the damage (90 s, then a `partial` packet) — but a recorded
demo cannot afford an 11/28 wipeout.

### 6. Multi-hop loop churn burns the wall budget on hard questions
`1a_004` (9 iters/36 s), `1b_003` (5 iters → 90 s timeout), `un_007` (6 iters → 90 s),
`1b_022` (66 s). The A3 critic keeps requesting more retrieval when the question's exact
noun phrase isn't in evidence, even when the answer's *value* is present. A churn guard
(stop after 2 iterations with no gold-relevant gain — the mechanism is already half-there
in `state.stagnant`) would cut latency and stop `1b_003`/`un_007` timing out.

### 7. The confidence display bug is still live
9 correct, verified answers show `confidence: 0.0`. `docs/reports/acceptance-2026-09-07.md`
recommends deriving confidence from `support` + entailment status in the verifier rather
than trusting the model's self-report — that is still the right fix and it is now blocking
a truthful confidence number on this eval too.

---

## Prioritised recommendations

| # | Change | Evidence from this run | Effort | Where |
|---|---|---|---|---|
| 1 | **A5: one citation per hop** on multi-hop claims; **A6: semantic (not literal) entailment for figure/portrait descriptions** | `1a_v12`, `1b_007`, `1b_009` — correct answers deleted/downgraded | M | `src/agents/composer.py` INSTRUCTION, `src/agents/verifier.py` `_entailment` |
| 2 | **A5: auto-bind the sole supporting figure** when a `requires_visual` claim has no `asset_ids`, instead of deleting it | `1a_v07`, `1a_v11`, `un_002` — composed nothing from a correctly retrieved image | S | `src/agents/composer.py` `_accept_draft` |
| 3 | **Contradiction intent: force a tier-1/codex-targeted retrieval pass; A3 may not report `sufficient` on single-tier evidence; run `detect_conflicts` on the pre-focus chunk set** | `1c_000` returned the tier-4 year as `corroborated`; both 1C packets have `conflicts: []` | M | `src/agents/retriever.py` `tune_for_intent`, `src/agents/critic.py`, `src/agents/merger.py` |
| 4 | **Churn guard**: stop the A2/A3 loop after 2 iterations with no gold-relevant gain and return a `partial` with the hop that *did* resolve | `1b_003`, `un_007` timed out at 90 s; `1a_004` took 9 iterations | S | `src/agents/orchestrator.py` `_loop` (extend `state.stagnant` logic) |
| 5 | **A5 responsiveness + wh-word check**: the composed claim's answer type must match the question ("whose" → agent, not place; and reject non-sequiturs) | `1b_013` (named the place, not the ruler), `un_008` (unrelated fact) | S | `src/agents/composer.py` |
| 6 | **Use `openai/gpt-4o` (OpenRouter) or a shared model id** so provider fallback engages | 11/28 questions wiped by one OpenAI connection drop | XS | run env / `.env` `LLM_MODEL_SYNTHESIS` |
| 7 | **Derive `confidence` from `support` + entailment** in A6; stop copying the `0.0` placeholder | 9 correct answers display `confidence: 0.0` | S | `src/agents/verifier.py` `_finish` |
| 8 | **Stop echoing answered sub-questions into `missing_information`** | `1a_001`, `1a_004`, `1b_006` correct answers flagged "unresolved" | XS | `src/agents/composer.py` `compose` |
| 9 | **LLM-extract `housed_at` / `located_in` edges** over the 6 infobox-less wiki articles | `1b_003` — hop 2 (`Aegis → Gloamreach`) is prose-only and was never surfaced | M | `src/graph/extract.py` scope |
| 10 | **Settle the `un_005` policy**: can an `atmo_*` portrait answer an "appearance" question when the text disclaims it? | `un_005` graded FAIL by the suite, PASS by the 7 Sept report | XS | `eval/suites/unanswerable.json` note + `docs/decisions.md` |

### What this run establishes for the submission narrative

- **Say plainly:** figure-plate 1A is measured and strong (6/6, traps included); the
  reasoning layer now produces real answers with per-claim citations; groundedness on the
  dev set is 0.75 and the gap to correctness is A6 strictness, not hallucination.
- **Do not claim:** multi-hop 1B is solved (3/7 clean here) or that 1C contradiction
  resolution is demonstrable (0/2 surfaced a conflict; 1/2 wrong value).
- **Fix before the freeze if nothing else:** recommendation #6 (provider fallback) and #2
  (portrait asset auto-bind) — both are small and each recovers whole questions.

---

## Acted on, 9 September — what changed and what it bought

Four of the ten recommendations were implemented and measured against this run. Every
change was verified against the eight-question demo regression set, which still passes.

| # | recommendation | outcome |
|---|---|---|
| 2 | A5: auto-bind the sole supporting figure | **done** — `1a_v11` FAIL to PASS, `1a_v12` borderline to PASS |
| 7 | derive confidence from support + entailment | **done** — real values replace `0.0` everywhere |
| 8 | stop echoing answered sub-questions | **done** — correct answers no longer marked partial |
| 4 | churn guard | **attempted and reverted**, see below |

### Recovered answers, verified against gold

```
1a_v11  gold 'a weeping eye'    -> 'a large open eye ... weeping golden'   1 claim, confidence 0.60
1a_v12  gold 'two crossed keys' -> 'two crossed keys on an ornate shield'  1 claim, confidence 0.75
1a_v06  gold 'a rolled scroll'  -> 'they are holding a rolled scroll'      1 claim, confidence 0.75
```

`1a_v07` still returns nothing, but for a different reason than before: the trace now
shows `asset_rebound`, so the figure *was* bound and the claim was then rejected by the
subject and value checks. That is the trap defence working, not the deletion bug.

### The trap defence was strengthened, not relaxed

The old test asserted that a visual claim with no `asset_id` must be discarded. That is
a **proxy** for safety - the model remembering an id - rather than the safety property,
which is that the value is bound to its subject. A new test now feeds a reference bar
**and** a forgotten asset id together: auto-binding hands the claim its figure, and
`bound_value` still refuses it. The Emberdeep trap in miniature, and it still holds.

### Recommendation 4 was reverted, deliberately

`1b_003` and `un_007` burn the full 90 s wall, and the obvious signal - the critic
requesting the same missing evidence twice running - turns out not to be sound. P2's
`SeventhStepCritic` test walks a list of records with an unchanging missing message
while making genuine progress each round; the guard stopped it at 3 of 6 steps.
Separating churn from progress needs the failing traces, which this run does not
preserve at that granularity. Shipping a guess that breaks a working feature test two
hours before a freeze is the wrong trade, so **finding 6 stays open**.

What did land from it: every give-up exit from the retrieval loop now names its reason.
Previously only the step-limit exit warned, so a run that stopped through stagnation was
indistinguishable in the trace from one that had genuinely gathered enough.

### Still open

Recommendations **1** (A5 one citation per hop, A6 semantic entailment for figure
descriptions), **3** (contradiction-intent retrieval), **5** (wh-word responsiveness),
**6** (provider fallback), **9** and **10**. Recommendation 1 remains the highest-value
of these and is the one most likely to move 1B.

---

## Model comparison, 9 September — measured, not assumed

Two questions were put after this run: would fine-tuning help, and is `gpt-5.6-luna`
better than `gpt-4o`. Both were tested rather than answered from opinion, and the
answer to each is **no**.

### `gpt-4o-mini` beats `gpt-4o` on this system

The headline result, and the opposite of the obvious assumption. Two questions, two
runs each, no caching between models:

| question | gold | `gpt-4o` | `gpt-4o-mini` |
|---|---|---|---|
| `1a_004` Thrice-Bound Edge | 94 | **0 claims**, twice | **94**, twice |
| `1c_000` Gloamreach | 246 AS (tier 1) | **286 AS**, twice - the tier-4 value | **246 AS**, twice |

This run was recorded on `gpt-4o`, so **it understates the system**. On `gpt-4o-mini`
all eight demo cases pass, including both that `gpt-4o` gets wrong.

It also reclassifies part of finding 4. `1c_000` returning the tier-4 year and calling
it corroborated is a **`gpt-4o` artefact**, not a defect in the contradiction layer -
the same code on `gpt-4o-mini` returns the tier-1 year. The rest of finding 4 (both 1C
packets carrying `conflicts: []`) still stands.

### `gpt-5.6-luna` end to end - worst of the three

The component tests below were run first and were **not sufficient**: they measured
isolated entailment calls and latency, never the whole pipeline. Corrected by running
the eight-question demo set on each model, same questions, same index:

| model | demo set | fails |
|---|---|---|
| **`gpt-4o-mini`** | **8/8** | - |
| `gpt-4o` | 6/8 | `1a_004` (0 claims), `1c_000` (286 AS, tier 4) |
| `gpt-5.6-luna` | **5/8** | `1a_004`, `1c_000`, `1c_003` (all 0 claims) |

Luna's three failures carry `budget_exhausted` and `tool_failure`, and `1a_004` also
`asset_unresolved` - it is not answering wrongly so much as failing to complete the
loop within budget. Newer and larger is not better here; the smallest model wins
outright.

### Component tests on luna, which pointed the wrong way


It exists on the key, with `gpt-5.6-sol` and `gpt-5.6-terra`. Three hypotheses tested,
all negative:

| hypothesis | result |
|---|---|
| better entailment | **no** - and the apparent gap was a mislabelled test: `contradicted` is a stronger rejection than `unsupported`, and `verifier.py` rejects on both |
| faster | **no** - warm median 1,983 ms (`gpt-4o`) vs 2,122 ms (luna); the 15.2 s first seen for `gpt-4o` was connection warmup |
| fixes the figure-entailment failure | **no** - both fail the same case identically |

One early sample showed `gpt-4o` answering `unsupported` where luna said `entailed`.
**It did not reproduce.** Recorded because a single sample like that is exactly how a
false claim gets into a report.

### Fine-tuning is the wrong move, on principle

CLAUDE.md's thesis is that the world is invented and anything the model *knows* about it
is hallucinated by definition - answers must come only from retrieved evidence. Training
the corpus into the weights destroys exactly that: **groundedness stops being
measurable**, because a retrieved answer and a memorised one become indistinguishable
and `claims[].support` means nothing. It would contradict the ADRs judges are reading as
the team's reasoning.

It would also not address the failures. They are structural - a forgotten `asset_id`, one
citation for a two-fact claim, a composer naming a place when asked for a person - not
gaps in what the model knows.

### Recommendation 1 was re-examined and is NOT being built as written

The A6 half of it - semantic rather than literal entailment for figure descriptions -
does not survive testing. An image-aware entailment prompt scores identically to the
current one (4/5 on five cases), and the shared failure is `gpt-4o` rejecting *"two
crossed **skeleton** keys"* against a description reading *"two crossed keys"* - which is
A6 being **correct**, since "skeleton" is an unsupported addition. `1a_v12`, the question
it was meant to fix, already passes.

The A5 half stands: given two excerpts for a two-fact claim, both models returned
`entailed`, so the fault is A5 attaching one citation to a two-hop claim, not A6
rejecting it.

---

## Clean re-run on the shipped code — 20 dev questions

Run against the code as submitted, on `gpt-4o-mini`, after the composer fixes. This is
the number set to quote; the earlier figures in this document were measured with a
`partial_without_missing_information` bug live.

| | before | **after** |
|---|---|---|
| packets with claims | 16/20 | **16/20** |
| empty answers | 4 | **4** |
| mean groundedness | 0.800 | **0.800** |
| gold coverage | 13/20 | **13/20** |
| lexical match *(diagnostic)* | 14 | **14** |
| **structural errors** | 3 | **0** |

Every number except structural errors is byte-identical across the two runs. That is the
point: the fix did exactly one thing and disturbed nothing else.

Against the 7 September baseline the movement is real — claims 13 to 16, empty 7 to 4,
groundedness 0.650 to 0.800 — and both 1C questions now answer *and* stay grounded.

**Caveat on latency.** The LLM cache was at a 69.9% hit rate (1,259 hits / 541 misses),
so the sub-second per-question times are not representative of a cold run. The answers
are unaffected — a cached response is the same response — but the timings are not a
benchmark. The durable cache counters added the same morning are the only reason this
was visible at all.

### The four remaining empty answers

| qid | gold coverage | recall | reading |
|---|---|---|---|
| `1b_005` | **True** | 1.00 | retrieval found everything; composition produced nothing |
| `1b_007` | **True** | 1.00 | same |
| `1a_v07` | False | 0.50 | figure bound then rejected by the subject/value guard |
| `1b_022` | False | 0.33 | genuine retrieval shortfall |

`1b_005` and `1b_007` are the ones that matter. Gold coverage `True` means the harness
confirmed the documents containing the answer *were* retrieved. The evidence was in
hand and A5 still wrote nothing — which is why neither better search, a larger model,
nor a knowledge graph would move them. It is recommendation 1: A5 attaches **one**
citation to a claim spanning **two** facts, so the claim cannot be supported and is
dropped.

Nothing implemented on 9 September touched that path, and these two are unchanged
across every run today. It remains the single highest-value open item.

---

## Multi-hop citations fixed — final 20-question run

| | this morning | **final** |
|---|---|---|
| packets with claims | 16/20 | **18/20** |
| empty answers | 4 | **2** |
| lexical match *(diagnostic)* | 14 | **16** |
| **mean groundedness** | 0.800 | **0.900** |
| structural errors | 0 | **0** |
| partial | 10 | 12 |

Gained `1a_v07`, `1b_007`, `1b_003`. Nothing lost. All eight demo cases unchanged.

### The cause was one quote spanning two chunks

Not the verifier, and not elision. A two-hop claim needs a fact per hop, and the model
states it as ONE elided quote tagged with ONE chunk id:

```
"...who serves as a Sapper... Ederon Fellgard is a member of..."
      ederon_fellgard:c0            ederon_fellgard:c2
```

No within-chunk match can succeed, so the claim died with all of its evidence sitting
in the bundle. Each fragment is now located in whichever retrieved chunk holds it and
cited separately — the one-citation-per-hop shape A6 wants. Nothing is invented: every
fragment must be a genuine verbatim span of a genuinely retrieved chunk.

### The first version of the fix was worse than the bug

`1b_007` went 0 to 1 claim, and the claim answered **hop 1 only** — *"Ederon Fellgard
is a member of The Iron-Ring Cartel"* to a question asking which **accord** that
faction won — while `partial` was False. The metrics improved at the exact moment the
behaviour got worse: a confident non-answer is worse than the honest refusal it
replaced. Caught by reading the answer, not the numbers.

A3's insufficiency verdict is now respected, so the packet keeps hop 1, stays partial,
and names what is still open.

### A1's intent labels are not trustworthy — a finding in their own right

Scoping that guard to multi-hop intents was tried and reverted, because A1 mislabels
the very questions it needed to catch:

| question | true shape | A1 says |
|---|---|---|
| `1b_007` | two-hop | **`direct`** |
| `1b_003` | multi-hop | **`exploratory`** |
| `1b_009` | multi-hop | `multi_hop` |

This matters beyond this fix: the per-intent retrieval policy keys off the same field,
so a 1B question labelled `direct` is being served the single-lookup configuration —
rerank on, graph expansion off — which is the worst measured row for multi-hop.
**Open, and probably the highest-value remaining item.**

The cost of reverting is that three correct answers (`1a_009`, `1a_v11`, `1a_v21`) are
flagged partial when they are complete. That is a presentation flaw; presenting a
half-answer as finished is a correctness failure. The conservative choice ships.

### Still empty, and correctly so

`1b_005` cites `the_ballad_concerning_the_war_of_drowned_light:c0`, a chunk not in the
bundle at all — fabrication, correctly refused. `1b_022` has gold coverage 0.33: a
genuine retrieval shortfall.

`1b_007`'s second hop also still fails, and that rejection is right. The model wrote
*"The declared victor of the [[The Leaden Accord]] was..."* where the novel reads
*"The Iron-Ring Cartel is declared victor of The Leaden Accord," Sabelle said* —
a paraphrase with invented wikilink brackets. Accepting it would destroy the one
property this system exists to guarantee.

---

## Reproduce

```bash
# knowledge API already running on :8000
LLM_MODEL_SYNTHESIS=gpt-4o KNOWLEDGE_API_URL=http://127.0.0.1:8000 \
  uv run uvicorn src.api.routes.chat:create_app --factory --host 127.0.0.1 --port 8001

# then POST each sample_questions.json entry (+ eval/suites/unanswerable.json) to
# :8001/v1/chat with {"question": ..., "mode": "auto", "budget": 12}
# and GET :8001/v1/traces/{X-Trace-ID} for the trajectory.
```

Raw packets + traces for all 28: `docs/reports/sample-questions-eval-2026-09-09.json`.
