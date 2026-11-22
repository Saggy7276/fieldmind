# FieldMind

A voice assistant that answers pump maintenance questions from the
*Improving Pumping System Performance* sourcebook (US DOE, 2006). Answers are
the manual's own sentences, read out with their section and page, so the
assistant cannot invent or contradict a fact. Questions outside the manual are
passed to a specialist instead of being answered.

**Live demo:** https://saggy7276.github.io/fieldmind/ — runs entirely in your
browser (first visit downloads ~110 MB of models, then they are cached). Voice
input needs Chrome or Edge; typing works everywhere.

## How it answers

1. **Guardrails on the question** — emergencies, prompt injection, empty input.
2. **Hybrid search** — MiniLM embeddings + BM25 keyword search, fused with RRF.
3. **Refusal** — if nothing in the manual is close enough, escalate.
4. **Sentence picking** — a cross-encoder (ms-marco MiniLM) scores the sentences
   of the retrieved sections; the best one or two are read out verbatim.

On the 35-question eval set: key fact in the answer 21/23, contradictions 0,
off-topic questions refused 12/12, ~0.7 s per answer on a laptop CPU.
Why it reads sentences instead of letting an LLM write answers:
[ADR 0003](docs/adr/0003-extractive-answers.md).

## Two ways to run

| | where | needs |
|---|---|---|
| Web app (`fieldmind-ui/`) | GitHub Pages or `npm run dev` | a browser |
| Python server (`fieldmind_optimized.py`) | your machine, fully offline | Python, models, optional Ollama |

```bash
# web app
cd fieldmind-ui && npm install && npm run dev
# point it at the Python server instead of the in-browser engine:
VITE_API_BASE=http://localhost:8000 npm run dev
```

The Python side (indexing, evaluation, server) is documented in
[docs/RAG.md](docs/RAG.md). After rebuilding the index, refresh the web app's
copy with `python deploy/export_web_index.py`; pushing to `main` redeploys the site.

## Layout

```
rag/            ingest, chunking, retrieval, guardrails, extractive answers, tracing
eval/           question set, retrieval benchmark, end-to-end evaluation
tests/          Python unit tests
fieldmind-ui/   React web app; src/engine/ is the in-browser port of the pipeline
deploy/         export of the index for the web app
docs/           run guide and architecture decision records
```
