# ADR 0001 — Chunking strategy for the FieldMind knowledge base

- **Status:** Accepted
- **Date:** 2026-11-19
- **Decision:** Section-aware chunking (≤160 words, 2-level heading breadcrumb in the chunk text, full path + page numbers in metadata) with hybrid dense + BM25 retrieval, top-4 chunks into the LLM.

## Context

Until now FieldMind's knowledge base was `about_me.txt`: five facts, one per line, one chunk per line.
That is fine for five facts. It is not fine for what field operators actually need answered, which is
what is in equipment manuals.

As the first real manual we ingested *Improving Pumping System Performance: A Sourcebook for Industry*
(US Department of Energy / Hydraulic Institute, 2nd ed. 2006) — a freely available 122-page PDF, ~47,000
words, with chapters, fact sheets, bullet-point maintenance checklists, tables, formulas and a glossary.
It is a realistic stand-in for the documents FieldMind will be given on site.

The constraints that shaped the decision:

1. **The embedder has a 256-token window.** `all-MiniLM-L6-v2` silently truncates longer input, so the
   tail of a long chunk is never searchable. With ~1.3 word pieces per English word, chunks must stay
   under ~160 words.
2. **The LLM is a 7B model on CPU.** Every word of context costs prompt-processing time before the first
   word is spoken. We cannot fix weak retrieval by stuffing 10 chunks into the prompt.
3. **Answers are spoken, 2–3 sentences.** The model needs a few *focused* chunks, not a broad sweep.
4. **Manuals have structure that carries meaning.** A checklist cut in half gives half the checks; a
   list separated from its intro line ("Operators should pay particular attention to the following:")
   loses what the list is about.
5. **Operators must be able to verify.** An answer needs a citation an operator can open: section and page.
6. **Questions are spoken and informal** ("how much leakage is okay on the packing"), the manual is formal.

## Options considered

All six are implemented in `rag/chunking.py` and selectable with `build_index.py --strategy`.

| Strategy | How it splits | Expected strength | Expected weakness |
|---|---|---|---|
| `line` | one chunk per line (previous behaviour) | trivial | PDF lines are fragments |
| `fixed` | 120-word window, 20-word overlap | simple, predictable size | cuts through lists and sentences |
| `sentence` | 4-sentence window, 1 overlap | never cuts a sentence | ignores sections |
| `recursive` | headings → paragraphs → lines → sentences until ≤160 words | respects structure where it can | no section context or citation |
| `semantic` | new chunk where neighbouring-sentence similarity drops | topic-coherent chunks | needs every sentence embedded; sensitive to short sentences |
| `section` | follows the heading tree, keeps lists/tables with their intro, splits long lists between items with one-item overlap, prefixes the heading path | structure + citations | needs headings in the input |

Because the PDF has no Markdown headings, `section` needed an ingestion step (`rag/ingest.py`) that
rebuilds the structure: the PDF bookmark outline gives chapters (with page ranges), a heading glyph the
sourcebook uses gives sub-sections, and running headers, side tabs, hyphenation and bullet glyphs are
cleaned up.

## How we evaluated

`eval/eval_rag.py` with `eval/questions.json`: 23 spoken-style questions (21 on the sourcebook, 2 on
`about_me.txt`). A chunk counts as relevant only if it contains the answer phrase **verbatim** (e.g.
`"60 drops per minute"`), so scoring needs no judgement. We also measure how many chunks exceed the
embedder's window and how many words reach the LLM.

## Results

Top-3, all strategies (`eval/results.md`):

| strategy | retrieval | hit@1 | hit@3 | MRR@3 | chunks | avg words | truncated | words to LLM |
|---|---|---|---|---|---|---|---|---|
| line | dense | 0.13 | 0.26 | 0.19 | 6863 | 7 | 0% | 31 |
| fixed | dense | 0.43 | 0.65 | 0.53 | 473 | 120 | 0% | 355 |
| fixed | hybrid | 0.39 | 0.83 | 0.59 | 473 | 120 | 0% | 355 |
| sentence | dense | 0.52 | 0.65 | 0.57 | 872 | 72 | 0% | 212 |
| sentence | hybrid | 0.43 | 0.70 | 0.55 | 872 | 72 | 0% | 213 |
| recursive | dense | 0.39 | 0.83 | 0.57 | 430 | 110 | 1% | 323 |
| recursive | hybrid | 0.30 | 0.87 | 0.56 | 430 | 110 | 1% | 337 |
| semantic | dense | 0.35 | 0.61 | 0.46 | 655 | 72 | 1% | 254 |
| semantic | hybrid | 0.39 | 0.61 | 0.49 | 655 | 72 | 1% | 289 |
| **section** | dense | 0.39 | 0.70 | 0.52 | 462 | 111 | 1% | 332 |
| **section** | **hybrid** | 0.30 | **0.87** | 0.53 | 462 | 111 | 1% | 345 |

Deeper retrieval, hybrid only:

| strategy | hit@4 | words to LLM @4 | hit@5 | words to LLM @5 |
|---|---|---|---|---|
| section | **0.91** | 461 | 0.91 | 568 |
| recursive | 0.87 | 451 | 0.96 | 553 |

## What we learned along the way

1. **The old line-per-fact approach does not survive a real document** (hit@3 0.26). PDF lines average
   7 words; no single line holds an answer.
2. **Semantic chunking was the most "intelligent" option and among the weakest** (0.61). On this manual,
   topic-shift detection between short sentences cut explanations in the middle, and it requires
   embedding every sentence at index time.
3. **The truncation metric caught a real bug.** Our first `section` version (hit@3 0.78) had 3% of its
   chunks over the 256-token window, up to 262 words, because a long intro sentence was repeated in front
   of every piece of a split list. Fixed; the max is now 160 words.
4. **A long breadcrumb hurt retrieval.** The first version wrote the full heading path into every chunk
   ("Improving Pumping System Performance (US DOE, 2006) > Section 2: … (p. 15-16) > Basic Pump
   Maintenance (p. 37-40) > …"). Hundreds of chunks sharing a 20-word prefix look alike to the embedder.
   After the bug fix we swept the number of levels: full path 0.74, 3 levels 0.74, 1 level 0.74,
   none 0.83, **2 levels 0.87**. The full path now lives in metadata, where it serves citations.
5. **Hybrid retrieval helps recall, not rank 1.** BM25 raised hit@3 for every strategy except `line` and
   `semantic` (section +0.17, fixed +0.18), because operators use exact terms (NPSHA, VFD, packing) that a
   small embedder blurs. It lowered hit@1 for four of the six strategies. So the LLM gets the top 4
   chunks rather than trusting the first.
6. **We did not tune the fusion weight.** A sweep of BM25 weights (1.0 / 0.7 / 0.5 / 0.3) moved results
   by at most one question. With 23 questions, that is noise, so we kept standard unweighted RRF.

## Decision

`section` chunking + hybrid retrieval, top-4, ≤160 words per chunk, 2-level breadcrumb.

`section` and `recursive` are statistically tied on retrieval with this test set (±1 question). We
chose `section` for what the benchmark does not measure but the operator experiences:

- **Citations.** Every chunk knows its chapter, sub-section and pages, so FieldMind can say where an
  answer came from, and the escalation message can point the operator to the right page.
- **Procedures stay whole.** Lists and tables are kept with their intro line; when a long list must be
  split, it is split between items, the intro is repeated and one item overlaps
  (`tests/test_chunking.py`).
- **The LLM sees where it is.** "[Basic Pump Maintenance > Common Failures]" at the top of a chunk tells
  the model the context of the text that follows.

## Consequences

- New documents must go through `rag/ingest.py` (PDF) or be Markdown with headings. Ingest heuristics
  were written against this sourcebook (e.g. its heading glyph U+E075); every new manual needs a look at
  its converted Markdown before indexing.
- The test set is small: one question is 4.3 percentage points. Before revisiting the strategy, grow
  `eval/questions.json` to 100+ questions, ideally from real operator transcripts in the trace log
  (see ADR 0002).
- Known misses with the chosen config: "how much leakage is okay on the pump packing", "how far can we
  trim down an impeller" (the right chunk ranks 5th+), and "what is FieldMind" (`about_me.txt` becomes one
  mixed chunk that scores below the refusal threshold).
