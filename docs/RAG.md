# FieldMind RAG — how to run it

```
knowledge_base/
  sources/doe_pump_sourcebook.pdf      original manual (US DOE, freely available)
  doe_pumping_sourcebook.md            structured Markdown produced by rag/ingest.py
rag/
  ingest.py         PDF → Markdown with headings and page ranges
  chunking.py       6 chunking strategies (default: section)
  retriever.py      hybrid dense + BM25 retrieval, RRF fusion, citations
  guardrails.py     input / retrieval / per-sentence output checks
  pipeline.py       question → guarded, cited, sentence-by-sentence answer
  extract.py        extractive answers: pick the manual sentence to read out
  observability.py  JSON trace log + /metrics
eval/
  questions.json    23 in-scope + 12 out-of-scope test questions, with key facts per answer
  eval_rag.py       chunking × retrieval benchmark + refusal-threshold sweep
  e2e.py            full pipeline on every question (key fact, contradictions, latency)
  results.md        latest benchmark output
  e2e_results*.md   end-to-end runs: current (extractive), _generative, _baseline
tests/              68 unit tests (no model or Ollama needed)
docs/adr/           why: 0001 chunking, 0002 guardrails & observability, 0003 extractive answers
```

**Answers are read out from the manual, not written by the LLM** (ADR 0003).
A cross-encoder picks the 1–2 manual sentences that answer the question, and they
are spoken verbatim. In the default mode the LLM (and Ollama) is not on the answer
path at all; `FIELDMIND_MODE=generative` brings back LLM-written answers.

Run from the project folder with the `voicebot` environment
(`voicebot\Scripts\activate`, or prefix commands with `voicebot\Scripts\python.exe`).

```bash
# 1. add a manual (PDF) -> Markdown; check the output before indexing
python -m rag.ingest knowledge_base/sources/doe_pump_sourcebook.pdf \
    --title "Improving Pumping System Performance (US DOE, 2006)" \
    --out knowledge_base/doe_pumping_sourcebook.md

# 2. build the index (default: section chunking); --show prints every chunk
python build_index.py
python build_index.py --strategy recursive       # try another strategy

# 3. measure
python -m eval.eval_rag                           # all strategies, dense vs hybrid
python -m eval.eval_rag --strategies section "section:crumb_levels=0" --k 4
python -m pytest tests -q
python -m eval.e2e                                # extractive (default): ~1 min, no Ollama needed
python -m eval.e2e --only 5,12                    # just those questions
python -m eval.e2e --mode generative --out eval/e2e_results_generative.md   # needs `ollama serve`; ~10 min

# 4. serve
uvicorn fieldmind_optimized:app --host 0.0.0.0 --port 8000
curl localhost:8000/health
curl localhost:8000/metrics
curl "localhost:8000/metrics?format=prom"
```

## Configuration (environment variables)

| variable | default | meaning |
|---|---|---|
| `FIELDMIND_MODE` | extractive | `extractive` = read out manual sentences; `generative` = LLM writes the answer |
| `FIELDMIND_SELECTOR` | reranker | extractive only: `reranker` (cross-encoder) or `llm` picks the sentence |
| `FIELDMIND_MIN_SCORE` | 0.375 | refuse (escalate) below this best-match cosine, unless dense and keyword search agree on a chunk containing every query term (floor 0.2) |
| `FIELDMIND_TOP_K` | 4 | chunks retrieved in generative mode (extractive searches 8) |
| `FIELDMIND_CONTEXT_WORDS` | 480 | generative only: max words of context sent to the LLM |
| `FIELDMIND_LLM` | fieldmind | Ollama model name |
| `FIELDMIND_LLM_TIMEOUT` | 60 | seconds before an LLM call is abandoned |
| `FIELDMIND_LOG_DIR` | logs | where `traces.jsonl` is written |
| `FIELDMIND_LOG_TEXT` | 1 | 0 = don't log question/answer text |

## API changes

`POST /ask` and the WebSocket `done` message now also return `reason`
(`ok`, `low_retrieval_confidence`, `ungrounded_number`, `emergency_keyword`,
`prompt_injection`, `model_escalated`, `no_answer_sentence`, `llm_unavailable`, …), `sources` and `trace_id`.

The reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`, ~80 MB) downloads on first
start like the embedding model; copy the Hugging Face cache to air-gapped machines.
Existing fields are unchanged.
