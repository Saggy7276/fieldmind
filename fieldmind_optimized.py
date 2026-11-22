"""
FieldMind — Optimized Backend
===============================
Key changes vs original:
  1. VAD (webrtcvad) replaces fixed 5s recording  → cuts dead-wait by ~3s
  2. pyttsx3 engine created ONCE at startup        → saves ~200ms per sentence
  3. TTS runs in ThreadPoolExecutor                → speech overlaps generation
  4. Whisper beam_size=1                           → ~40% faster transcription
  5. RAG retrieval fires before streaming starts   → no extra serial wait
  6. FastAPI WebSocket streams tokens to frontend  → browser speaks as it arrives

Reliability layer (rag/):
  7. Section-aware chunking + hybrid (dense + BM25) retrieval  → rag/chunking.py, rag/retriever.py
  8. Guardrails: emergency / injection / low-confidence refusal,
     sentence-level number grounding before anything is spoken → rag/guardrails.py
  9. LLM retry with backoff, HTTP timeout, low temperature     → rag/pipeline.py
 10. Per-request JSON traces + /metrics (JSON or Prometheus)    → rag/observability.py
 11. Answers carry source citations (section + page)

Install:
  pip install fastapi uvicorn webrtcvad sounddevice faster-whisper
              ollama chromadb sentence-transformers pyttsx3 numpy pypdf

Build the index first:
  python build_index.py

Run:
  uvicorn fieldmind_optimized:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import chromadb
import numpy as np
import ollama
import pyttsx3
import sounddevice as sd
import webrtcvad
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from faster_whisper import WhisperModel
from pydantic import BaseModel
from sentence_transformers import CrossEncoder, SentenceTransformer

from rag.observability import METRICS
from rag.pipeline import DEFAULT_SYSTEM_PROMPT, RERANK_MODEL, FieldMindPipeline, PipelineConfig
from rag.retriever import Retriever

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG  (override with environment variables)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EMBED_MODEL   = "all-MiniLM-L6-v2"
LLM_MODEL     = os.getenv("FIELDMIND_LLM", "fieldmind")
OLLAMA_HOST   = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_TIMEOUT_S = float(os.getenv("FIELDMIND_LLM_TIMEOUT", "60"))
# Refusal threshold on best-match cosine; chosen from eval/eval_rag.py
# (see docs/adr/0002-guardrails-and-observability.md).
MIN_SCORE     = float(os.getenv("FIELDMIND_MIN_SCORE", "0.375"))
# top-4 section chunks: hit@4 = 0.91 vs hit@3 = 0.87 on eval/questions.json,
# ~460 context words. Raise only after measuring LLM prompt time on site hardware.
TOP_K         = int(os.getenv("FIELDMIND_TOP_K", "4"))
CONTEXT_WORDS = int(os.getenv("FIELDMIND_CONTEXT_WORDS", "480"))
# extractive: speak the manual's own sentence, the LLM only picks which one
# (no paraphrase errors; see rag/extract.py). generative: the LLM writes the answer.
ANSWER_MODE   = os.getenv("FIELDMIND_MODE", "extractive")
SELECTOR      = os.getenv("FIELDMIND_SELECTOR", "reranker")  # extractive: reranker | llm

SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT  # shared with eval/e2e.py

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STARTUP — load everything once
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("⚡ Loading FieldMind (optimized)…")

# STT — beam_size=1 cuts latency ~40 % with negligible quality loss
stt = WhisperModel("base", device="cpu", compute_type="int8")

# RAG
embedder = SentenceTransformer(EMBED_MODEL)
rag_client = chromadb.PersistentClient(path="./rag_db")
rag_collection = rag_client.get_collection("about")
INDEX_INFO = dict(rag_collection.metadata or {})
if INDEX_INFO.get("embed_model", EMBED_MODEL) != EMBED_MODEL:
    raise RuntimeError(
        f"Index was built with {INDEX_INFO['embed_model']} but the server uses {EMBED_MODEL}. "
        "Re-run build_index.py."
    )
retriever = Retriever.from_chroma(rag_collection, embedder, mode="hybrid")
print(f"   index: {len(retriever)} chunks, strategy={INDEX_INFO.get('strategy', 'unknown')}, "
      f"built={INDEX_INFO.get('built_at', 'unknown')}")

# LLM — HTTP timeout so a hung Ollama can't hang the operator forever
llm_client = ollama.Client(host=OLLAMA_HOST, timeout=LLM_TIMEOUT_S)


def ollama_stream(messages: list[dict]):
    stream = llm_client.chat(
        model=LLM_MODEL,
        messages=messages,
        stream=True,
        options={"temperature": 0.1, "num_predict": 200},  # factual, short
    )
    for chunk in stream:
        yield chunk["message"]["content"]


reranker = None
if ANSWER_MODE == "extractive" and SELECTOR == "reranker":
    _cross_encoder = CrossEncoder(RERANK_MODEL)
    reranker = lambda q, texts: _cross_encoder.predict([(q, t) for t in texts])

pipeline = FieldMindPipeline(
    retriever,
    ollama_stream,
    PipelineConfig(system_prompt=SYSTEM_PROMPT, min_score=MIN_SCORE, top_k=TOP_K, context_words=CONTEXT_WORDS,
                   mode=ANSWER_MODE),
    reranker,
)

# TTS — ONE engine for the whole process lifetime
_tts_engine = pyttsx3.init()
_tts_engine.setProperty("rate", 175)
_tts_lock = threading.Lock()          # pyttsx3 is not thread-safe
_tts_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")

# VAD
_vad = webrtcvad.Vad(2)              # aggressiveness 0-3 (2 = balanced)

print("✅ FieldMind ready.\n")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VAD LISTENER  (replaces fixed 5 s recording)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SAMPLE_RATE   = 16_000
FRAME_MS      = 30          # webrtcvad accepts 10 / 20 / 30 ms frames
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)   # 480 samples
MAX_SILENCE_FRAMES = int(700 / FRAME_MS)             # 700 ms trailing silence → stop
MAX_RECORD_FRAMES  = int(8_000 / FRAME_MS)           # 8 s hard cap


def listen_vad() -> str:
    """
    Record until speech ends (VAD) instead of a fixed duration.
    Returns transcribed text or empty string.
    """
    print("🎤 Listening (VAD)…", flush=True)
    frames: list[np.ndarray] = []
    silence_count = 0
    speech_started = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype="int16", blocksize=FRAME_SAMPLES) as stream:
        for _ in range(MAX_RECORD_FRAMES):
            frame, _ = stream.read(FRAME_SAMPLES)
            pcm = frame[:, 0].tobytes()           # int16 PCM bytes
            is_speech = _vad.is_speech(pcm, SAMPLE_RATE)

            if is_speech:
                speech_started = True
                silence_count = 0
                frames.append(frame[:, 0])
            elif speech_started:
                silence_count += 1
                frames.append(frame[:, 0])        # keep trailing audio
                if silence_count >= MAX_SILENCE_FRAMES:
                    break                         # speech ended
            # if not started yet, skip (don't record pre-speech silence)

    if not frames:
        return ""

    audio = np.concatenate(frames).astype("float32") / 32768.0
    segments, _ = stt.transcribe(audio, language="en", beam_size=1)
    return " ".join(seg.text for seg in segments).strip()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TTS — non-blocking, overlaps with generation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _speak_blocking(text: str) -> None:
    """Runs in the single TTS thread. Engine kept alive — no re-init cost."""
    with _tts_lock:
        _tts_engine.say(text)
        _tts_engine.runAndWait()


def speak_async(text: str):
    """Submit a sentence to the TTS thread and return immediately."""
    _tts_executor.submit(_speak_blocking, text)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CORE PIPELINE  (standalone / CLI / REST)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def ask_streaming(question: str, channel: str = "cli", speak: bool = True) -> dict:
    """
    Run the guarded pipeline; speak each sentence as soon as it has passed the
    guardrails. TTS fires in background thread — overlaps with generation.
    """
    print("🤖 FieldMind: ", end="", flush=True)
    done: dict = {}
    for event in pipeline.run(question, channel=channel):
        if event["type"] == "sentence":
            print(event["text"], end=" ", flush=True)
            if speak:
                speak_async(event["text"])
        else:
            done = event
    print()
    if done.get("sources"):
        print(f"   sources: {'; '.join(done['sources'])}")
    return done


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FASTAPI  (for frontend)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
app = FastAPI(title="FieldMind Optimized API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/health")
def health():
    try:
        llm_client.list()
        llm_ok = True
    except Exception:
        llm_ok = False
    return {
        "status": "online" if llm_ok else "degraded",
        "llm_reachable": llm_ok,
        "index": {"chunks": len(retriever), **INDEX_INFO},
        "min_score": MIN_SCORE,
        "timestamp": _now(),
    }


@app.get("/metrics")
def metrics(format: str = "json"):
    if format == "prom":
        return PlainTextResponse(METRICS.prometheus())
    return METRICS.snapshot()


class QuestionRequest(BaseModel):
    question: str


@app.post("/ask")
def ask_rest(req: QuestionRequest):
    done = ask_streaming(req.question, channel="rest", speak=False)
    return {
        "question": req.question,
        "answer": done.get("answer", ""),
        "escalate": done.get("escalate", True),
        "reason": done.get("reason"),
        "sources": done.get("sources", []),
        "trace_id": done.get("trace_id"),
        "latency_s": done.get("latency_s"),
        "timestamp": _now(),
    }


@app.websocket("/ws/ask")
async def ws_ask(websocket: WebSocket):
    """
    Protocol (unchanged for the existing UI, new fields are additive):
      → {"type":"token","content":...}  text that has passed the guardrails
      → {"type":"speak","sentence":...} same sentence, for browser TTS
      → {"type":"done","escalate":bool,"reason":...,"sources":[...],"trace_id":...}
    Text is released one checked sentence at a time, not token by token, so a
    sentence that fails the number-grounding check is never shown or spoken.
    """
    await websocket.accept()
    loop = asyncio.get_running_loop()
    try:
        while True:
            payload  = json.loads(await websocket.receive_text())
            question = payload.get("question", "")
            queue: asyncio.Queue = asyncio.Queue()

            def run_pipeline():
                try:
                    for event in pipeline.run(question, channel="ws"):
                        loop.call_soon_threadsafe(queue.put_nowait, event)
                except Exception as e:  # never leave the client waiting
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(e)})

            threading.Thread(target=run_pipeline, daemon=True).start()

            first = True
            while True:
                event = await queue.get()
                if event["type"] == "sentence":
                    text = event["text"] if first else " " + event["text"]
                    first = False
                    await websocket.send_json({"type": "token", "content": text})
                    await websocket.send_json({"type": "speak", "sentence": event["text"]})
                elif event["type"] == "done":
                    await websocket.send_json({**event, "timestamp": _now()})
                    break
                else:
                    await websocket.send_json(event)
                    await websocket.send_json({"type": "done", "escalate": True, "reason": "server_error",
                                               "timestamp": _now()})
                    break

    except WebSocketDisconnect:
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CLI LOOP  (run without FastAPI: python fieldmind_optimized.py --cli)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    import sys
    if "--cli" in sys.argv:
        speak_async("Field Mind online.")
        try:
            while True:
                question = listen_vad()
                if not question:
                    print("(silence — retrying)")
                    continue
                print(f"🧑 Operator: {question}")
                done = ask_streaming(question)
                if done.get("escalate") and done.get("reason") != "emergency_keyword":
                    speak_async("Transferring you to a specialist now.")
        except KeyboardInterrupt:
            print("\n👋 FieldMind stopped.")
    else:
        import uvicorn
        uvicorn.run("fieldmind_optimized:app", host="0.0.0.0", port=8000, reload=True)
