# Limitations — what this system does not do, with the number

`docs/evaluation.md` §9 commits to recording these *as they are measured*, not on the last
day from memory. Everything below is either a measurement on the real archive or an
explicit statement that no measurement exists yet.

Ordered by how much it would cost us if a judge found it first.

---

## 1. The answer layer is unmeasured

**Retrieval is measured. Answers are not.** `groundedness`, `citation_precision`,
`correctness` and `refusal_accuracy` are defined in `docs/evaluation.md`, implemented in
`eval/metrics.py` and unit-tested — against synthetic inputs. **No number has been
produced from a real answer**, because A5 (Composer) and A6 (Verifier) are not built yet.

A green regression gate today proves the retriever did not get worse. It proves nothing
about answer quality. That distinction is written here rather than left for someone to
infer from a table of retrieval scores.

---

## 2. Reranking makes multi-hop retrieval worse

The most important negative result we have.

| | 1A nDCG@10 | 1A MRR | 1B recall@10 | 1B coverage@10 |
|---|---|---|---|---|
| Hybrid RRF | 0.715 | 0.803 | 0.714 | 0.429 |
| Hybrid + cross-encoder rerank | **0.779** | **0.939** | **0.500** | **0.143** |

Rerank is a clear win on single-lookup and figure questions and a **two-thirds loss of
coverage** on multi-hop.

The mechanism: a cross-encoder scores each document's relevance to the query
*independently*. A 1B question needs documents that are individually weak matches and
collectively necessary — the second hop's article often does not mention the question's
subject at all. The reranker correctly judges those less relevant and demotes exactly the
evidence the answer requires.

**Status: measured, and no longer the only option.** Graph expansion reaches 0.905
recall / 0.714 coverage on the same suite at 20 ms, against the reranker's 0.500 /
0.143 at 2.4 s - so the multi-hop path does not need the cross-encoder at all.

The remaining fix is intent-conditioned rerank — on for
`figure` and `lookup`, off for `multihop` — which is why the router takes `intent` from A1
rather than always applying the strongest pipeline. Until that lands, the default config
(`4. Hybrid + rerank`) is the wrong default for 1B, and we know it.

Full table and per-question failures: `docs/reports/ablation.md`.

---

## 3. Multi-hop coverage is 0.714 — better, and still the headline weakness

Graph expansion moved this from 0.429 to **0.714** (recall 0.714 -> 0.905). Five of seven
multi-hop questions now have all their gold documents in the top 10.

**Two still do not**, and no composer can answer those correctly. That is 29% of the
sub-track this system calls its spine.

The ceiling is structural rather than incidental: graph expansion seeds on entities named
in the question, so a question that names none gets nothing from it (see section 12). The
next lever is LLM-extracted edges over `chronicles/` and `ephemera/`, which widen what one
hop can reach.

---

## 4. The gold sets are small, and we wrote them

- `multihop_1b`: **7** questions · `rich_1a`: **11** · `contradiction_1c`: **2**
- `sample_questions.json` ships **no gold answers**. Every label is hand-authored by us
  from the corpus.

Consequences, stated plainly:

- On 1B, **one question is worth 0.143 of coverage.** A 0.143 move is one question
  changing its mind, not a trend. Nothing smaller than about two questions is worth
  arguing over.
- On 1C, n = 2. Every 1C number in this repo is directional. The row where hybrid scores
  0.500 against BM25's 1.000 is *one question* — do not read it as a fusion defect.
- We know the corpus, so our questions inherit our blind spots. A hidden set written by
  someone else will not share them. Every gold label cites the document and line it came
  from so a reader can check it; that is mitigation, not a fix.

---

## 5. The chunk-size sweep has not produced a number yet

ADR-008 sets 450 tokens from the embedding model's 512-token context, not from a sweep.
The evidence for changing was a *defect*, not a comparison: at 600 tokens, **173 chunks
(8.8%) were indexed but only partly embedded** — present in the store, unreachable by
dense retrieval, with nothing logged.

That justifies leaving 600. It does not establish that 450 beats 300 or 400.

**Status: `scripts/chunk_sweep.py` now runs it**, into isolated indexes so the working one
is never at risk. Results land in `docs/reports/chunk-sweep.json`. Until they do, 450
remains a defensible derivation rather than a measured winner - and if 300 turns out to
beat it, that is a finding to report rather than a number to bury.

---

## 6. The graph's vocabulary is wiki-derived, and only the vocabulary

**198 entities and 379 relations, all from 95 wiki articles**, at the time the ablation in
`docs/reports/ablation.md` was run. `chronicles/` (four novels) and `ephemera/` (46
records) contributed **zero** edges.

`src/graph/extract.py` now closes this, over 849 narrative passages naming two or more
known entities. It is closed-vocabulary in both directions - endpoints must be entities the
wiki already knows and that are already named in the passage, predicates must come from the
frozen list - so the model is never asked who exists, only how the entities in front of it
relate.

**What that does not fix:** an entity that appears *only* in a novel is still absent
entirely, because the vocabulary itself is wiki-derived. Extraction adds edges between
known entities; it does not discover new ones. That is a deliberate trade - discovering
entities from prose is where invented proper nouns get invented - and it is still a hole.

Entity resolution is **article-stripping and nothing else**: "The Iron-Ring Cartel" and
"Iron-Ring Cartel" merge, nothing else does. Deliberate — broader fuzzy matching is what
turns `greyfell_citadel` (garrison 3,695) into `ironfell_citadel` (1,096), two real places
one edit apart with different numbers. The price is that a genuine alias we have not seen
resolves to nothing, and the system reports `resolved: false` instead of answering.

---

## 7. Conflict detection has known precision and unknown recall

**7 conflicts found corpus-wide**, each verified by hand against both source documents, so
precision is 7/7 on what it reports. **Recall is unknown**, and we are not going to claim
otherwise: stating it needs a gold set of every contradiction in the archive, which means
reading 1,248 pages.

Extraction is pattern-based rather than an LLM call, which bounds the failure direction:
patterns miss conflicts (silent, recoverable) rather than invent them (loud, and a
hallucinated disagreement manufactures doubt about facts nobody disputes). Three classes of
false positive were caught and fixed during development — a person given a founding year,
`'none recorded'` against `'none recorded'`, and `'4672 troops'` against `'4672'`. That is
evidence the pattern layer needed the guards it now has, not evidence that it has enough
of them.

---

## 8. Image understanding rests on one model and one pass

- **70 unique images**, each described once by `minimax/minimax-m3:free`, cached.
- **Gold recovery is 11/11 — on 11 questions, not 70 images.** **59 of the 70 descriptions
  have never been checked against anything.**
- No second model cross-checks a description. A confidently wrong `values[]` binding would
  flow into an answer carrying a real citation and look exactly like a right one.
- The vision ladder has untested rungs. The 11/11 is on the free primary; if it is
  unavailable during judging, the fallback's accuracy on these plates is an assumption.

Tesseract is not a substitute: it recovers **3 of 11** gold answers and reads **zero
characters on 54 of 55** `atmo_*` images. On the trap plate it reads every label at 95%
confidence and none of the numbers. Full comparison: `docs/reports/ocr-vs-vlm.md`.

---

## 9. Structure extraction is 93.8%, not 100%

PDF/DOCX outline agreement is **93.8%**, after adding bold-weight detection to font-size
clustering took it from 72.2%. The residual is document titles on pages with no text layer.

A heading the extractor misses becomes a wrong `section_path` on every chunk beneath it — a
citation pointing at the right document and the wrong section.

OCR recovered **39 blocks at median 0.952 confidence** and took documents yielding zero
blocks from 15 to 0. No page fell below the 0.75 confidence threshold, so the VLM fallback
for scanned pages **has never actually executed** on this corpus — it is code we believe in
rather than code we have watched work.

---

## 10. Latency

- Warm search: **76 ms** without rerank, **1,106 ms** with.
- Under eval load, rerank p95 reaches **2,500–4,600 ms** across runs — and buys **no
  recall at all** on 1A (0.773 with and without). It buys rank position only.

Retrieval fits the budget. End-to-end latency, with an agent loop and a composer on top, is
unmeasured because the loop does not exist yet.

---

## 11. Environment assumptions that can fail on someone else's machine

| Assumption | What happens when it is false |
|---|---|
| Tesseract on PATH | OCR degrades to empty, the run continues, 15 documents lose their text |
| Qdrant reachable at `QDRANT_URL` | dense retrieval returns `[]` — the harness now **refuses to score** rather than reporting 0.000 |
| Vectors built into *that* store | the same failure; the embedded store and the service do not share data |
| Vision model reachable | cached descriptions still serve; a new image falls down the ladder |
| Qdrant client/server versions aligned | a compatibility warning on every run — pinned to v1.15.4 in `docker-compose.yml`; the client is 1.19.0 and the warning is cosmetic but present |

The Qdrant row exists because it already happened. A full ablation ran to completion and
printed `dense@10 = 0.000` across every suite because the vectors lived in a different
store; an absent collection returns `[]` rather than raising. `EmptyIndexError` and the
vector count on `/v1/ready` are that incident turned into a guard.

---

## 12. Multi-hop strength depends on the question naming an entity we know

The `paraphrase` suite re-asks questions whose answers we already have, in wordings we
did not write, against identical gold documents. On the 1B subset (n = 14):

| | original wording | paraphrased |
|---|---|---|
| Hybrid RRF | 0.429 | 0.143 |
| + graph expand | 0.714 | **0.429** |

**Rewording costs about 0.29 of coverage.** Graph expansion recovers roughly the same
amount either way; it just starts from a lower base. 1A is untouched (0.600 both ways) -
a plate lookup does not care how the question is phrased.

By style, under graph expansion: colloquial 5/9, formal 2/3, terse 2/5, **oblique 0/2**.

The oblique cases are the honest weakness. Those two questions deliberately name no
canonical entity - "the great worm of the marrow-fens" instead of "the Gravemaw Wyrm" -
so graph expansion finds no seed and contributes **nothing**. The question falls back to
base retrieval, which was already failing it.

This is structural, not a tuning problem. Expansion seeds on exact, article-insensitive
entity matches and there is no fuzzy fallback, because a fuzzy fallback is how
`greyfell_citadel` becomes `ironfell_citadel` (Finding 13). So the system is strong on
multi-hop **when the question names something we can match** and no better than plain
hybrid retrieval when it does not.

Two consequences worth stating before a judge finds them:

- A1's normalisation against the published vocabulary is load-bearing. It is the only
  thing that can turn an oblique question into one the graph can seed from.
- A hidden set phrased more obliquely than ours would move these numbers down, and we
  have measured how far: to roughly the hybrid-only baseline.

---

## Approaches abandoned, and the number that killed each

| Abandoned | Killed by |
|---|---|
| 600-token chunks | 173 chunks (8.8%) indexed but silently truncated at the embedder's 512-token context |
| Indexing PDF and DOCX twins separately | identical extracted text — one source would look to A4's tier logic like two corroborating sources |
| Embedded Qdrant as primary | single-process: an index build held the lock and the API could not open the store |
| Fuzzy entity matching | `greyfell_citadel` (3,695) and `ironfell_citadel` (1,096) are one edit apart and different places |
| Density-only scan routing | all 17 scans are named `*.scan.pdf`; the convention is exact, so the heuristic is kept only as a fallback |
| Font-size-only heading detection | 19 of the Annals' 82 headings are bold at body size — 72.2% → 93.8% once weight was added |
| LLM-extracted conflicts | an invented disagreement is unfalsifiable; pattern extraction is verifiable by opening two documents |

---

## Not measured at all

Named here so that "we did not measure it" is a recorded fact rather than a gap someone
else finds:

- the agent loop without the redundancy guard (`evaluation.md` §9) — the loop is P2's and
  is not built
- `success@budget`, `avg_steps`, `gain_per_step` — same reason
- ablation row 8, the conflict layer: A4 exists and is tested, but nothing consumes it into
  an answer yet, so its effect on an answer is unmeasured
- end-to-end 1A answer accuracy; only *retrieval of the right plate* is measured today
- the quality of LLM-extracted graph edges: the five validators are tested and the drop
  counts are reported, but no human has checked a sample of the KEPT edges against their
  source passages. Precision on what survives validation is therefore unknown, which is
  the same gap section 7 admits for conflicts

Measured since this file was first written, and no longer on this list: paraphrase
robustness (section 12), ablation rows 5–7 (`docs/reports/ablation.md`), and row 9, which
is running.
