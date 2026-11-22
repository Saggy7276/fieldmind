# 0003 — Read out the manual's sentence instead of an LLM-written answer

Status: accepted, 2026-11-21

## Context

End-to-end runs (`eval/e2e.py`, 23 in-scope questions) with Mistral-7B writing the
answer from retrieved context:

| run | key fact in answer | contradicts the manual | first sentence (median) |
|---|---|---|---|
| original prompt (`e2e_results_baseline.md`) | 17/23 | 1 | 11.2 s |
| tightened prompt (`e2e_results_generative.md`) | 19/23 | **2** | 12.7 s |

The contradictions are the dangerous failure for a field assistant:

- "Should I start the centrifugal pump with the discharge valves closed?" The manual
  says starting deadheaded *reduces* electrical stress on the motor; the model said
  it causes it, in both runs, despite a prompt telling it to follow the manual.
- "How far can we trim an impeller?" The model said "up to 2%", lifted from a worked
  example; the manual's limit is "rarely below 70% of the original size". The number
  guardrail cannot catch this: 2% *is* in the context.

(The original report of 10/23 was mostly the metric: it required the manual sentence
verbatim, so correct paraphrases failed. `questions.json` now has `answer_facts`
— short facts with accepted wordings — and `must_not` phrases that flag a contradiction.)

## Decision

Default to **extractive answers** (`rag/extract.py`):

1. Retrieve 8 chunks (hybrid, unchanged), split them into sentence units. Short
   follow-ups and "This/It…" sentences stay with the sentence before them; checklist
   items stand alone; glossary runs are split per entry; figure captions, axis labels,
   formulas, lead-ins ending in ":" and mid-sentence fragments are dropped.
2. Shortlist 30 units (dense cosine + query-term overlap, RRF).
3. A cross-encoder (`ms-marco-MiniLM-L-6-v2`) scores them; the best is spoken
   verbatim, plus the second only if it scores within 1.0 and is not a repeat.

The retrieval refusal guardrail is unchanged, apart from the keyword-agreement rescue
(dense and BM25 agree on a chunk containing every query term, cosine ≥ 0.2), which
recovered "what do the affinity laws describe" and "what is FieldMind" without letting
any out-of-scope question through.

## Alternatives measured

| selector | key fact | contradictions | latency |
|---|---|---|---|
| cross-encoder, adaptive 1–2 sentences (**chosen**) | **21/23** | **0** | **0.7 s** median, 1.0 s max |
| Mistral-7B picks a sentence number | 2/5 spot check | 0 | 6–15 s |
| LLM-written answer | 19/23 | 2 | 12.7 s to first sentence |
| more context for the LLM (k=5, 600 words) | recovers 1 retrieval miss | — | ~25% more prompt |

The LLM selector was tried first: even with a worked example in the prompt it chose
sentences that shared words with the question rather than ones that answered it.

## Consequences

- An answer can no longer contradict or misquote the manual; the worst case is an
  unhelpful but true sentence. Remaining misses: "how far can we trim an impeller"
  (the reranker prefers "operating far from its design point"; the 70% sentence
  scores −2.1) and "what happens if all the valves after a positive displacement pump
  are closed" (answer says "overpressure", the expected "relief valve" is not read).
- Answers sound like the manual, not like a conversation, and may start with the
  manual's item label ("Packing. Check for leakage…").
- Ollama is off the answer path in the default mode; the server still uses it for
  `FIELDMIND_MODE=generative` and `FIELDMIND_SELECTOR=llm`.
- One more model to ship (~80 MB) to air-gapped sites.
- `about_me.txt` was rewritten in the third person (original in `older/`), since its
  sentences are now spoken as written.
- The selection heuristics were tuned on the same 23 questions they are scored on;
  expect a lower rate on new questions. Add questions to `eval/questions.json`
  before tuning further.
