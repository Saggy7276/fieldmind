"""
The FieldMind question → answer pipeline, independent of audio and transport.

    for event in pipeline.run(question, channel="ws"):
        event = {"type": "sentence", "text": ...}   # safe to display / speak
        event = {"type": "done", "escalate": ..., "reason": ..., "sources": [...], ...}

Stages (each timed in the trace, each able to stop the pipeline):
  1. input guardrail       emergency / injection / empty / rambling
  2. retrieval             hybrid dense + BM25, top-k chunks within a word budget
  3. retrieval guardrail   refuse when the best match is below MIN_SCORE
  4. LLM stream            retried with backoff if it fails before the first token
  5. sentence gate         each sentence is checked before it is released, so a
                           hallucinated number is never spoken

Two answer modes (PipelineConfig.mode):
  extractive (default)  a cross-encoder (or, without one, the LLM) picks which
                        manual sentences answer the question; they are spoken
                        verbatim (rag/extract.py)
  generative            the LLM writes its own answer from the context
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

from rag import extract as ex
from rag import guardrails as g
from rag.observability import Trace
from rag.retriever import Retriever

LLMStream = Callable[[list[dict]], Iterable[str]]

# Split after . ! ? followed by whitespace, but not after a bare list number ("1. ").
_BOUNDARY = re.compile(r"(?<=[^\d\s][.!?])\s+")
_ARTIFACTS = re.compile(r"\[/?INST\]|<</?SYS>>|</?s>")
_LEADING_JUNK = re.compile(r"^[^a-zA-Z0-9\"'(]+")

DEFAULT_SYSTEM_PROMPT = (
    "You are FieldMind, a voice assistant for field operators. "
    "Answer ONLY from the manual excerpts in the context. "
    "First find the excerpt sentence that answers the question, then say it in your first sentence, "
    "keeping the manual's own wording, technical terms and exact figures (percentages, intervals, limits). "
    "If the manual says something different from what you would expect, follow the manual. "
    "Add at most one more short sentence, only if it is in the context. No lists, no general advice. "
    "Never invent numbers, limits or intervals that are not in the context. "
    "When referring to the developer or creator of this system, always use the name Sagar and refer to him "
    "in third person — never say 'you' when describing him. "
    "If the context does not contain the answer, or the query is out of scope, respond with exactly: ESCALATE"
)

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"  # ~80 MB, downloaded once, then offline

LLM_FAILURE_MESSAGE ="I lost the connection to the language model. I'm passing this to a specialist."


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", _ARTIFACTS.sub("", text)).strip()


def pop_sentences(buffer: str) -> tuple[list[str], str]:
    parts = _BOUNDARY.split(buffer)
    return [p for p in parts[:-1] if p.strip()], parts[-1]


@dataclass
class PipelineConfig:
    system_prompt: str
    min_score: float = 0.375
    keyword_floor: float = 0.2
    top_k: int = 4
    context_words: int = 480
    max_retries: int = 2
    retry_backoff_s: float = 0.5
    mode: str = "extractive"          # or "generative"
    extract_top_k: int = 8            # chunks searched for sentences (only sentences reach the LLM)
    extract_candidates: int = 8       # sentences shown to the LLM (LLM selector)
    rerank_candidates: int = 30       # sentences scored by the cross-encoder (reranker selector)
    extract_max_picks: int = 2


class FieldMindPipeline:
    def __init__(self, retriever: Retriever, llm_stream: LLMStream, config: PipelineConfig,
                 reranker: ex.Reranker | None = None):
        self.retriever = retriever
        self.llm_stream = llm_stream
        self.cfg = config
        self.reranker = reranker  # extractive mode: picks the sentence; without one the LLM picks

    def run(self, question: str, channel: str = "api") -> Iterator[dict]:
        trace = Trace(channel, question)
        try:
            yield from self._run(question.strip(), trace)
        finally:
            trace.finish("aborted")  # no-op if the run already finished

    # ------------------------------------------------------------------ #
    def _stop(self, trace: Trace, verdict: g.Verdict, sources=None, extra_sentences=()) -> Iterator[dict]:
        yield {"type": "sentence", "text": verdict.message}
        escalate = verdict.action in (g.ESCALATE, g.EMERGENCY)
        trace.event(f"guardrail.{verdict.reason}")
        answer = " ".join([*extra_sentences, verdict.message])
        trace.finish(verdict.action, reason=verdict.reason, escalate=escalate, answer=answer)
        yield self._done(trace, escalate, verdict.reason, sources or [], answer)

    @staticmethod
    def _done(trace: Trace, escalate: bool, reason: str, sources: list[str], answer: str) -> dict:
        return {
            "type": "done",
            "escalate": escalate,
            "reason": reason,
            "sources": sources,
            "answer": answer,
            "trace_id": trace.id,
            "latency_s": round(trace.since_start_ms() / 1000, 2),
        }

    def _run(self, question: str, trace: Trace) -> Iterator[dict]:
        # 1. input guardrail
        verdict = g.check_input(question)
        if not verdict.ok:
            yield from self._stop(trace, verdict)
            return

        # 2. retrieval
        extractive = self.cfg.mode == "extractive"
        with trace.span("retrieve"):
            result = self.retriever.search(question, top_k=self.cfg.extract_top_k if extractive else self.cfg.top_k)
        context = result.context(self.cfg.context_words)
        trace.set(retrieval={"mode": result.mode, "top_dense": round(result.top_dense, 4),
                             "keyword_match": result.keyword_match, "hits": result.log_view()})

        # 3. retrieval guardrail
        verdict = g.check_retrieval(result.top_dense, self.cfg.min_score,
                                    result.keyword_match, self.cfg.keyword_floor)
        if not verdict.ok:
            yield from self._stop(trace, verdict)
            return

        if extractive:
            yield from self._extractive(question, result, trace)
            return

        messages = [
            {"role": "system", "content": self.cfg.system_prompt},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ]

        # 4. LLM stream with retry  +  5. sentence gate
        released: list[str] = []
        buffer = ""
        t_llm = time.perf_counter()
        for attempt in range(self.cfg.max_retries + 1):
            got_tokens = False
            try:
                for piece in self.llm_stream(messages):
                    if not got_tokens:
                        got_tokens = True
                        trace.add_span("llm_first_token", (time.perf_counter() - t_llm) * 1000)
                    buffer += piece
                    sentences, buffer = pop_sentences(buffer)
                    for s in sentences:
                        verdict, text = self._gate(s, released, context, question, trace)
                        if verdict is not None:
                            yield from self._stop(trace, verdict, result.sources, released)
                            return
                        if text:
                            yield {"type": "sentence", "text": text}
                break
            except Exception as exc:  # network error, Ollama restart, timeout
                trace.event("llm_error", attempt=attempt, error=f"{type(exc).__name__}: {exc}"[:300])
                if got_tokens or attempt == self.cfg.max_retries:
                    failure = g.Verdict(g.ESCALATE, "llm_unavailable", LLM_FAILURE_MESSAGE)
                    yield from self._stop(trace, failure, result.sources, released)
                    return
                time.sleep(self.cfg.retry_backoff_s * (2 ** attempt))
                t_llm = time.perf_counter()
        trace.add_span("llm", (time.perf_counter() - t_llm) * 1000)

        if buffer.strip():
            verdict, text = self._gate(buffer, released, context, question, trace)
            if verdict is not None:
                yield from self._stop(trace, verdict, result.sources, released)
                return
            if text:
                yield {"type": "sentence", "text": text}

        answer = " ".join(released)
        if not answer:
            yield from self._stop(trace, g.Verdict(g.ESCALATE, "empty_answer", g.ESCALATE_MESSAGE), result.sources)
            return

        ratio = g.grounding_ratio(answer, context)
        trace.finish("answer", reason="ok", escalate=False, answer=answer, grounding_ratio=round(ratio, 3))
        yield self._done(trace, False, "ok", result.sources, answer)

    def _extractive(self, question: str, result, trace: Trace) -> Iterator[dict]:
        n = self.cfg.rerank_candidates if self.reranker else self.cfg.extract_candidates
        with trace.span("candidates"):
            cands = ex.candidate_sentences(question, result.hits, self.retriever.embed_batch, n)
        if not cands:
            yield from self._stop(trace, g.Verdict(g.ESCALATE, "empty_answer", g.ESCALATE_MESSAGE), result.sources)
            return

        if self.reranker:
            with trace.span("rerank"):
                picks, scores = ex.rerank_picks(question, cands, self.reranker, self.cfg.extract_max_picks)
            trace.set(selection={"selector": "reranker", "picks": [cands[i].hit.id for i in picks],
                                 "scores": [round(scores[i], 2) for i in picks]})
            yield from self._speak(question, result, ex.order_picks(picks, cands), trace)
            return

        # The LLM answers with a number; stop reading as soon as the first line is complete.
        messages = ex.selection_messages(question, cands)
        output = ""
        t_llm = time.perf_counter()
        for attempt in range(self.cfg.max_retries + 1):
            output = ""
            try:
                for piece in self.llm_stream(messages):
                    if not output:
                        trace.add_span("llm_first_token", (time.perf_counter() - t_llm) * 1000)
                    output += piece
                    if "\n" in output.strip() or len(output) > 40:
                        break
                break
            except Exception as exc:
                trace.event("llm_error", attempt=attempt, error=f"{type(exc).__name__}: {exc}"[:300])
                if attempt == self.cfg.max_retries:
                    failure = g.Verdict(g.ESCALATE, "llm_unavailable", LLM_FAILURE_MESSAGE)
                    yield from self._stop(trace, failure, result.sources)
                    return
                time.sleep(self.cfg.retry_backoff_s * (2 ** attempt))
                t_llm = time.perf_counter()
        trace.add_span("llm", (time.perf_counter() - t_llm) * 1000)

        picks = ex.parse_picks(output, len(cands), self.cfg.extract_max_picks)
        trace.set(selection={"selector": "llm", "output": output.strip()[:60], "picks": [p + 1 for p in picks],
                             "candidates": [c.hit.id for c in cands]})
        if not picks:
            yield from self._stop(trace, g.Verdict(g.ESCALATE, "no_answer_sentence", g.ESCALATE_MESSAGE),
                                  result.sources)
            return
        yield from self._speak(question, result, ex.order_picks(picks, cands), trace)

    def _speak(self, question: str, result, chosen: list, trace: Trace) -> Iterator[dict]:
        context = "\n\n".join(h.text for h in result.hits)
        released: list[str] = []
        for c in chosen:
            verdict, text = self._gate(ex.speakable(c.text), released, context, question, trace)
            if verdict is not None:  # cannot fire on a verbatim sentence, kept as a backstop
                yield from self._stop(trace, verdict, result.sources, released)
                return
            if text:
                yield {"type": "sentence", "text": text}

        answer = " ".join(released)
        sources = list(dict.fromkeys([c.hit.citation for c in chosen] + result.sources))
        trace.finish("answer", reason="ok", escalate=False, answer=answer, grounding_ratio=1.0)
        yield self._done(trace, False, "ok", sources, answer)

    @staticmethod
    def _gate(sentence: str, released: list[str], context: str, question: str,
              trace: Trace) -> tuple[g.Verdict | None, str]:
        """Clean and check one sentence -> (stop verdict or None, cleaned text).
        Approved text is appended to `released`; empty text is skipped."""
        text = clean(sentence)
        if not released:
            text = _LEADING_JUNK.sub("", text)
        if not text:
            return None, ""
        verdict = g.check_sentence(text, context, question)
        if not verdict.ok:
            trace.event("sentence_blocked", reason=verdict.reason,
                        numbers=sorted(g.ungrounded_numbers(text, context, question)))
            return verdict, text
        released.append(text)
        return None, text
