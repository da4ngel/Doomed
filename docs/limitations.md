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

**Status: measured, not yet mitigated.** The fix is intent-conditioned rerank — on for
`figure` and `lookup`, off for `multihop` — which is why the router takes `intent` from A1
rather than always applying the strongest pipeline. Until that lands, the default config
(`4. Hybrid + rerank`) is the wrong default for 1B, and we know it.

Full table and per-question failures: `docs/reports/ablation.md`.

---

## 3. Multi-hop coverage is 0.429, and that is the headline weakness

Under the best current config, **3 of 7 multi-hop questions have all their gold documents
in the top 10.** The other four cannot be answered correctly however good the composer is:
`1b_022`, `1b_007`, `1b_013`, `1b_003`.

recall@10 on the same run is 0.714, which sounds survivable. It is the same run. Reporting
recall alone would have hidden this — which is the argument for `coverage@k` existing.

Graph expansion (ablation row 6) exists to fix precisely this and **is not yet wired into
the retrieval path**. 0.429 is the number it has to beat.

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

## 5. The chunk-size sweep was never run

ADR-008 sets 450 tokens from the embedding model's 512-token context, not from a sweep.
The evidence for changing was a *defect*, not a comparison: at 600 tokens, **173 chunks
(8.8%) were indexed but only partly embedded** — present in the store, unreachable by
dense retrieval, with nothing logged.

That justifies leaving 600. It does not establish that 450 beats 300 or 400. Ablation row
9 (300 / 450 / 600) is unrun; each size costs one ~20-minute re-index.

---

## 6. The graph only knows what the wiki states

**198 entities, 379 relations, all from 95 wiki articles.** `chronicles/` (four novels)
and `ephemera/` (46 records) contribute **zero** edges — LLM extraction over them is
specified and not built.

An entity whose only relationship is asserted in a novel or a letter is therefore absent
from the graph, and graph-based multi-hop cannot reach it. Building deterministic and free
before probabilistic and expensive was the right order (ADR-005). It is still a coverage
hole.

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
- paraphrase robustness: every gold question is phrased once, by us
- ablation rows 5–9 (context expansion, graph expansion, agent loop, conflict layer, chunk
  sweep)
- end-to-end 1A answer accuracy; only *retrieval of the right plate* is measured today
