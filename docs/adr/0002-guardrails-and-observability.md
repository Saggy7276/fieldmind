# ADR 0002 — Guardrails, reliability and observability

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

FieldMind talks to people working on live equipment. Two properties of that setting drive this ADR:

- **A wrong, confident answer is worse than no answer.** An invented bearing-temperature limit or
  lubrication interval can damage equipment or hurt someone. "I don't know, I'm passing this to a
  specialist" is always an acceptable outcome; the system already had an `ESCALATE` path for it.
- **Speech cannot be taken back.** In a chat UI a bad sentence can be edited away. Once the TTS engine
  has said it, the operator has heard it.

And one constraint: **FieldMind is air-gapped.** No hosted tracing or monitoring service is available;
everything has to work locally.

Before this change the only safeguard was the system prompt asking the model to say `ESCALATE`.

## Decision 1 — Layered guardrails (`rag/guardrails.py`, `rag/pipeline.py`)

Each layer can stop the pipeline. The cheap ones run first, and the LLM only runs if they all pass.

| Layer | Check | On failure |
|---|---|---|
| Input | empty / under 3 characters (VAD picked up noise) | ask to repeat |
| Input | over 60 words (rambling or a mis-transcription) | ask for one short question |
| Input | **emergency words** (fire, smoke, electric shock, gas leak, injured, …) | fixed safety message **immediately, without the LLM**, escalate |
| Input | prompt-injection patterns ("ignore previous instructions", "reveal your prompt", …) | refuse |
| Retrieval | best cosine match below `MIN_SCORE` | escalate **without calling the LLM** |
| Prompt | "use ONLY the context, never invent numbers, else say ESCALATE"; temperature 0.1, max 200 tokens | — |
| Output, per sentence | the model said `ESCALATE` | escalate |
| Output, per sentence | **a number in the sentence appears neither in the retrieved context nor in the question** | stop before the sentence is spoken, escalate |
| Output | grounding ratio (share of answer words found in context) | logged only |

**Why gate per sentence.** FieldMind already speaks sentence by sentence, so the next sentence plays
while the model is still generating. The gate sits exactly at that boundary: a sentence is checked, then
displayed and spoken. Nothing unchecked reaches the operator, and no latency is added beyond the
sentence buffering the TTS already did. The cost is that the browser now receives text a sentence at a
time instead of a token at a time. The WebSocket message types are unchanged, so the existing UI works
as is.

**Why numbers.** In maintenance answers, numbers are where a hallucination does harm (limits, intervals,
torques, clearances), and they are the easiest thing to verify mechanically. Prose is paraphrased
legitimately, so the word-overlap ratio is only logged.

### Choosing `MIN_SCORE`

`eval/eval_rag.py` also embeds 12 out-of-scope questions (weather, email passwords, PLC configuration,
car oil, motor wiring colours, …) and sweeps the threshold:

| threshold | in-scope refused (of 23) | out-of-scope answered (of 12) |
|---|---|---|
| 0.300 | 2 | 2 |
| 0.350 | 2 | 1 |
| **0.375** | **2** | **0** |
| 0.450 | 3 | 0 |
| 0.550 | 5 | 0 |

The highest out-of-scope score is 0.351 ("how do I configure a Siemens S7 PLC"); 90% of in-scope
questions score above 0.424. **0.375** is the lowest threshold that answers no out-of-scope question.
The two in-scope refusals are "what is FieldMind" (0.212) and "what do the affinity laws describe" (0.266).
The threshold is overridable with `FIELDMIND_MIN_SCORE`.

### What the smoke test showed

Running the real index with a scripted LLM, the correct answers to "how much leakage is okay on the
packing" ("2 to 60 drops per minute") and "how far can we trim an impeller" ("below 70%") were **blocked**
by the number check, because retrieval had not surfaced the chunk containing those figures. That is the
guardrail working as designed: a retrieval miss becomes an escalation, not a guess. It was also the
reason for raising retrieval from top-3 to top-4 (hit@4 0.91 vs hit@3 0.87, see ADR 0001).

## Decision 2 — Reliability of the LLM call

- **HTTP timeout** on the Ollama client (`FIELDMIND_LLM_TIMEOUT`, default 60 s). A hung model can no
  longer hang the operator.
- **Retry with exponential backoff** (2 retries, 0.5 s → 1 s) when the call fails *before the first
  token*, e.g. while Ollama restarts. After tokens have been spoken, a failure escalates instead of
  retrying, so the operator never hears the start of an answer twice.
- **Index/model consistency check at startup.** `build_index.py` stores the chunking strategy, the
  embedding model, the build time and the source documents in the collection metadata. The server refuses
  to start if the index was built with a different embedder, which would give silently meaningless scores.
  `/health` reports which index is deployed and whether the LLM is reachable.
- **Citations** in every response (`sources`: document > chapter (pages) > section).

## Decision 3 — Local observability (`rag/observability.py`)

- **One JSON line per request** in `logs/traces.jsonl` (rotated at 20 MB): trace id, channel, timings
  (`retrieve`, `llm_first_token`, `llm`, `total`), retrieved chunk ids with dense/BM25/fused scores, the
  best match score, every guardrail event (including *which* numbers were ungrounded), the outcome, the
  grounding ratio, and the question and answer text.
- **`GET /metrics`**: request and outcome counters plus p50/p95/max latency per stage, as JSON, or in
  Prometheus text format with `?format=prom` for a site that runs a local Prometheus/Grafana.
- **Privacy:** `FIELDMIND_LOG_TEXT=0` keeps question and answer text out of the log.

The trace log doubles as the source of the next evaluation set. Escalations with
`low_retrieval_confidence` near the threshold are the questions to add to `eval/questions.json`.

## End-to-end run with the real model

`python -m eval.e2e`: all 35 questions through the pipeline with the `fieldmind` (Mistral-7B Q4) model
on Ollama, on the development laptop's CPU. Full table: `eval/e2e_results.md`.

| | result |
|---|---|
| Out-of-scope questions escalated | **12 / 12** (all at the retrieval guardrail, so the LLM never ran) |
| In-scope answered | 20 / 23 (2 refused at the threshold, 1 blocked by the number check) |
| Answers judged correct against the manual (manual review) | 18 of the 20 answered |
| Time to first spoken sentence (answered) | median 11.2 s, max 14.4 s (first question after a cold start: ~100 s) |
| Total answer time | median 17.6 s, max 26.2 s |

The script's automatic "expected fact" check (answer contains the exact manual phrase) scored only 10/23,
because the LLM paraphrases. Correctness above therefore comes from reading each answer against the manual.

What the run found:

1. **Guardrail false positive, fixed.** "How do I check the mechanical seal" was blocked on the number
   `1`. The model had written a numbered list ("1. Inspect the seal…"). List markers are now excluded
   from the number check (regression test in `tests/test_guardrails.py`). On re-run the question is
   answered.
2. **A dangerous wrong answer the guardrails did not catch.** Asked "should I start the centrifugal pump
   with the discharge valves closed", the model said it is *not recommended* because it causes
   electrical stress. The manual (p. 41-44) says the opposite: starting deadheaded and opening the
   valves once the pump is up to speed *reduces* electrical stress. All the right facts were in the
   context, but the model inverted the conclusion. No number was involved, so the number check could not
   see it.
3. **One non-answer.** "How far can we trim an impeller" got the affinity-law rule of thumb instead of
   the 70% limit. The numbers in it were real, so the answer is grounded but doesn't answer the question.
4. **Answers are longer than asked.** Despite "2-3 sentences" in the prompt, list-style answers run to
   7 steps. That is acceptable on screen but long to listen to.

## Limitations (known, not yet addressed)

- **Inverted or contradicted statements are not detected** (finding 2 above). Candidate fixes, both
  costing latency on CPU: a second LLM pass that checks each sentence against the context (supported /
  contradicted / not found), or a small local NLI (entailment) model run per sentence.

- The number check misses spelled-out numbers ("sixty"), swapped units, and wrong numbers that *do*
  appear somewhere in the context.
- Emergency and injection patterns are English keyword lists.
- `MIN_SCORE` was chosen on the same 35 questions it is reported on.
- The e2e check of answer correctness is manual; an automatic judge is needed before the question set
  grows past a few dozen.
- The HTTP server path (`/ask`, WebSocket, `/metrics`) was compiled but not started during this work.
  The pipeline it calls was tested end to end as above.
