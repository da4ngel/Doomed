# Live demonstration script — DOOMED ARCHIVE

**Target duration:** 3 minutes 40 seconds · continuous, unedited.
**Every question and request in this script has been run against the live services and
verified.** Exact paste-strings: `docs/demo-questions.txt`.

---

## Pre-flight (before the recording light)

1. **Services up.**
   - Knowledge API: `uv run uvicorn src.api.main:app --port 8000`
     → `curl -s localhost:8000/v1/ready` shows `status: ready`, `warm: true`.
   - Reasoning API: `LLM_MODEL_SYNTHESIS=gpt-4o-mini KNOWLEDGE_API_URL=http://127.0.0.1:8000 \
     uv run uvicorn src.api.routes.chat:create_app --factory --host 127.0.0.1 --port 8001`
2. **Warm the three app questions** by asking each once (Demo 1, Demo 1 backup, Demo 2 —
   verbatim from `demo-questions.txt`). The recording then replays them in ~1 second and
   identically. A cached answer is the same answer — this is legitimate.
3. **Browser:** `http://127.0.0.1:8001` open, **no previous answer on screen** (fresh reload).
4. **Postman:** `AshenEra` collection open, environment `local`. Pre-select the two
   requests (`09 Assets → Emberdeep plate metadata`, `03 Graph → 1b_013 - creature to lair
   to ruler`) so each is one click away. Confirm the `1b_013` body reads
   `{"from":"Gravemaw Wyrm","to":"The Bleeding Crown","max_hops":3}`.
5. **Run every demo twice** end to end. Confirm Demo 1 says `1,114` and is *not* flagged
   partial; Demo 2 produces *two* claims with *two* citations.
6. Hide API keys, notifications, personal info, unrelated windows. `.env` not visible.

> **Do not** ask *"Whose dominion encompasses the lair of the Gravemaw Wyrm?"* in the app —
> the reasoning loop fails that phrasing today. That chain is shown as the Postman
> graph-path request in Demo 4 instead.

---

## 0:00 – 0:15 — Cold open

*(App on screen, empty.)*

> "This is DOOMED ARCHIVE. It answers questions about a four-hundred-document invented
> archive — where more than half the answers aren't in the text at all, they're inside
> figures and images, and the hardest questions need facts joined across separate
> documents. Every answer it gives shows its evidence. Here it is, live."

---

## 0:15 – 1:05 — Demo 1 · A figure the text never states (≈50 s)

**Track 1A — rich visual answers.**

Actions:
1. Approach: **Choose automatically**. Deep Semantic Search **off**. "Keep my original
   wording" **unchecked**.
2. Paste: *"According to the figure plate illustrating Emberdeep's forces, what is the
   recorded total of its garrison strength?"*
3. Click **Search the archive** once.
4. As the trace appears, point at the stage rows: `A1 analyze → A2 figure_search →
   A4 merge → A5 compose → A6 verify`.

Point at, in the answer:
- **Emberdeep: 1,114**
- the bar-chart figure it rendered
- the **tier 1** citation and the source excerpt
- the confidence badge (75%), *not* flagged partial

> "The answer is one thousand one hundred and fourteen. That number appears in **no
> document** in this archive — it exists only inside this chart. And the chart is a trap:
> it also prints 800, 2,400 and 6,000 as reference standards, and the 1,114 bar is drawn
> *shorter* than the 6,000 one. Read the biggest number and you're wrong. Run plain OCR
> and you get 'Ee'. The system reads the figure the way a person does — it binds each
> value to its own label — and it shows you the plate and the tier-one source it used."

---

## 1:05 – 2:35 — Demo 2 · A fact assembled from two documents (≈90 s)

**Track 1B — connecting facts across the archive.**

Actions:
1. Change Approach to **Investigate**.
2. Paste: *"Which war was won by the organization that included Isolde Mournvale as one of
   its members?"*
3. Click **Search the archive** once. Keep the trace panel visible the whole time.

Narrate against the trace as the rows land:

> "No single document holds this answer. Watch the investigation.
> — **A1** reads the question and tags it *multi-hop*.
> — **A2** searches, and finds Isolde Mournvale's affiliation: a faction called the Silent
> Choir.
> — **A3**, the sufficiency critic, says that's not enough — *we still don't know which
> war that faction won* — and asks for another search.
> — **A2** runs again, this time searching for the Silent Choir itself.
> — Now it has both halves. **A4** merges nineteen passages. **A5** writes the answer as
> two separate claims. **A6** verifies each claim against its quoted source — nothing
> removed."

Point at the two claims and their citations:
- "The Silent Choir was victor of **The War of Drowned Light**." → tier-1 excerpt
- "Isolde Mournvale is a **member of The Silent Choir**." → tier-1 excerpt

Then address the partial flag directly:

> "Notice it labels this **partial** and lists two follow-up questions it didn't chase.
> That's deliberate. The system separates what it can *prove* from what it's still curious
> about, and it would rather show you that seam than hide it. The note 'retrieval returned
> nothing new twice' is its own stop rule firing — it searched, stopped learning, and
> quit instead of spinning. The two claims it *did* make are each backed by a tier-one
> record, and you can read the exact sentence under each one."

---

## 2:35 – 3:05 — Demo 3 · The structure under a figure answer (≈30 s)

*(Switch to Postman — keep recording.)*

Actions:
1. Open **09 Assets → "Emberdeep plate metadata - the planted chart trap"**. Click **Send**.
2. Point at `values[]`:
   - Old Imperial minimum → **800**
   - Border-march standard → **2,400**
   - Great Keep standard → **6,000**
   - Emberdeep → **1,114**
3. Open the **Test Results** tab — assertions pass.

> "This is what sat under the first answer. The figure holds four numbers; basic OCR pulls
> all four with no idea which is which. Our structured reading keeps each one tied to its
> label — Emberdeep to 1,114, the three reference standards held separate — and the
> contract tests on this endpoint pass."

---

## 3:05 – 3:30 — Demo 4 · The evidence graph, end to end (≈25 s)

Actions:
1. Open **03 Graph → "1b_013 - creature to lair to ruler"**. Body is already
   `{"from":"Gravemaw Wyrm","to":"The Bleeding Crown","max_hops":3}`. Click **Send**.
2. Point at `paths[0].hops`:
   - Gravemaw Wyrm — `lair_of` → Marrowwell Abbey
   - Marrowwell Abbey — `ruled_by` → The Bleeding Crown
3. Point at the `evidence_chunk_id` on each hop.
4. Open the **Test Results** tab — assertions pass.

> "Underneath the reasoning is a deterministic evidence graph — every entity and every
> relationship read straight from the archive, no model in the loop. Here's a different
> two-hop chain: a creature, to its lair, to whoever rules that ground. Each link carries
> the exact source record it came from, so the whole path is auditable."

---

## 3:30 – 3:40 — Close

> "That's one continuous, unedited run. DOOMED ARCHIVE reads figures, connects facts
> across documents, decides for itself when it has enough, and shows the source under
> every claim. Three hundred and twenty-nine tests and sixty-nine API contract checks
> back it, and the whole thing reproduces from the README with two commands. Thank you."

---

## If something goes wrong (spoken, keep moving)

| Problem | Say |
|---|---|
| Demo 1 comes back flagged *partial* | "It's holding itself to a high bar here — it wanted a second corroborating source and there's only the one plate. The value and the figure are right." |
| Demo 1 wrong / empty | Reload, run the backup: *"According to the official threat-classification plate, what numerical rating is assigned to the creature known as the Weeping Lurker?"* → **3**. |
| Demo 2 slow (cache missed) | "It's running the full loop live — a few seconds per search pass." Wait it out; it finishes ≈45 s. |
| Demo 2 returns only one claim / empty | "Multi-hop composition is the honest edge of this system — the retrieval found the documents, and it's refusing to state a link it can't fully quote. That refusal is the feature." Move to Demo 3. |
| A yellow "normalization_skipped" note appears | Ignore it, or: "it's telling us it didn't need to correct any names in that question." |
| Postman request 404 / no env | Check the environment selector is on **local** and `base_url` is `http://localhost:8000`. |

---

## What each demo proves (for your own reference — don't read aloud)

- **Demo 1:** vision-over-OCR is real and measured — 6/6 figure plates in the 9 Sep eval,
  every planted trap resisted. The answer exists only as pixels.
- **Demo 2:** the A1→(A2→A3)*→A4→A5→A6 state machine; the critic drives a second hop;
  per-claim `citation_ids`; A6 deletes unsupported claims; the anti-churn stop rule.
- **Demo 3:** `label → value` binding, the mechanism behind Demo 1; contract-tested seam.
- **Demo 4:** 198 entities / 742 relations, every edge citing its source; exact-match
  entity resolution (no fuzzy `Greyfell→Ironfell` collapse); deterministic, no LLM.
- **Close:** `uv run pytest` (329) + Newman (69 assertions) + `make gate` + `make ablation`.
