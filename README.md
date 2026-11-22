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
# Python side
python -m pip install -r requirements.txt
# web app
cd fieldmind-ui && npm install && npm run dev
# point it at the Python server instead of the in-browser engine:
VITE_API_BASE=http://localhost:8000 npm run dev
```

## Recreating it from scratch

Tested with Python 3.12 and Node 22–24. The manual PDF and its Markdown
conversion are in the repo; the index, models and virtual environment are not,
and are rebuilt by these steps.

**1. Clone and set up Python**

```bash
git clone https://github.com/Saggy7276/fieldmind.git
cd fieldmind
python -m venv voicebot
voicebot\Scripts\activate          # Windows
# source voicebot/bin/activate     # macOS / Linux
python -m pip install -r requirements.txt
```

**2. Build the search index** (creates `rag_db/`; the first run downloads the
MiniLM embedding model, ~90 MB)

```bash
python build_index.py
```

To start over from the PDF (for example with a different manual), convert it
first, then check the Markdown before indexing:

```bash
python -m rag.ingest knowledge_base/sources/doe_pump_sourcebook.pdf \
    --title "Improving Pumping System Performance (US DOE, 2006)" \
    --out knowledge_base/doe_pumping_sourcebook.md
```

**3. Check it works**

```bash
python -m pytest tests -q          # 68 unit tests, no models needed
python -m eval.e2e                 # full eval, ~1 min; expect key fact 21/23, 0 contradictions
```

The first eval run also downloads the cross-encoder (~80 MB).

**4. Run the voice server**

```bash
uvicorn fieldmind_optimized:app --host 0.0.0.0 --port 8000
curl localhost:8000/health
```

The default extractive mode needs no LLM. For the optional generative mode
(`FIELDMIND_MODE=generative`), install [Ollama](https://ollama.com), download
`mistral-7b-instruct-v0.3.Q4_K_M.gguf` from Hugging Face into the project
folder, and register it under the name the server expects:

```bash
ollama create fieldmind -f Modelfile
ollama serve
```

**5. Run the web app**

```bash
cd fieldmind-ui
npm install
npm run dev                        # in-browser engine at http://localhost:5173
```

If you changed the manual or rebuilt the index, refresh the web app's copy of it
first (from the project folder):

```bash
python deploy/export_web_index.py
```

**6. Publish your own copy on GitHub Pages**

Push the repo to your GitHub account, then in **Settings → Pages** set
**Source** to **GitHub Actions**. The workflow in `.github/workflows/pages.yml`
builds the web app on each push to `main` and publishes it at
`https://<your-user>.github.io/<repo-name>/` (the path follows the repo name).

## More detail

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
