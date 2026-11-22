"""Pipeline tests with a fake embedder and a fake LLM — no Ollama, no model download."""

import json

import numpy as np
import pytest

from rag import observability
from rag.pipeline import FieldMindPipeline, PipelineConfig, pop_sentences
from rag.retriever import BM25, Retriever, rrf, tokenize

DOCS = [
    "[Basic Pump Maintenance > Checklist]\nAllowable leakage is usually between 2 and 60 drops per minute.",
    "[Centrifugal Pumps > NPSH]\nNPSHA is the available suction head; NPSHR is required by the pump.",
    "[Impeller Trimming > Limitations]\nImpeller diameters are rarely reduced below 70% of their original size.",
]
VOCAB = ["leakage", "drops", "npsh", "npsha", "impeller", "trim", "packing"]


def fake_embed(text: str) -> np.ndarray:
    t = text.lower()
    v = np.array([t.count(w) for w in VOCAB], dtype=np.float32) + 0.01
    return v / np.linalg.norm(v)


@pytest.fixture(autouse=True)
def tmp_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(observability, "LOG_DIR", tmp_path)
    return tmp_path


def make_pipeline(llm_pieces=None, llm=None, min_score=0.3, mode="generative"):
    emb = np.stack([fake_embed(d) for d in DOCS])
    r = Retriever([f"c{i}" for i in range(3)], DOCS,
                  [{"section": d.split("]")[0][1:] + " (p. 1)"} for d in DOCS], emb, fake_embed)

    def default_llm(messages):
        yield from llm_pieces

    cfg = PipelineConfig(system_prompt="sys", min_score=min_score, retry_backoff_s=0, mode=mode)
    return FieldMindPipeline(r, llm or default_llm, cfg)


def run(p, q):
    events = list(p.run(q, channel="test"))
    return [e["text"] for e in events if e["type"] == "sentence"], events[-1]


def test_pop_sentences_does_not_split_list_numbers_or_decimals():
    done, rest = pop_sentences("1. Open the valve. Pressure is 3.5 bar. Then")
    assert done == ["1. Open the valve.", "Pressure is 3.5 bar."]
    assert rest == "Then"


def test_tokenizer_keeps_tags():
    assert "v-101b" in tokenize("Close valve V-101B now")


def test_bm25_prefers_exact_term():
    bm = BM25(DOCS)
    assert int(np.argmax(bm.scores("NPSHA"))) == 1


def test_keyword_match_flag():
    r = make_pipeline([]).retriever
    assert r.search("impeller limitations", top_k=2).keyword_match      # both rankers agree, all terms present
    assert not r.search("impeller gearbox", top_k=2).keyword_match      # 'gearbox' not in the chunk


def test_rrf_fuses_rankings():
    fused = rrf([[0, 1, 2], [1, 0, 2]])
    assert fused[0] == pytest.approx(fused[1]) and fused[2] < fused[0]


def test_grounded_answer_streams_with_sources(tmp_logs):
    p = make_pipeline(["Allowable leakage ", "is 2 to 60 drops per minute. ", "Adjust the packing."])
    sentences, done = run(p, "how much leakage is okay")
    assert sentences == ["Allowable leakage is 2 to 60 drops per minute.", "Adjust the packing."]
    assert done["escalate"] is False and done["reason"] == "ok"
    assert done["sources"][0].startswith("Basic Pump Maintenance")
    trace = json.loads((tmp_logs / "traces.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert trace["outcome"] == "answer" and "retrieve" in trace["spans_ms"] and "llm_first_token" in trace["spans_ms"]


def test_hallucinated_number_is_never_released():
    p = make_pipeline(["Leakage is fine. ", "Up to 120 drops per minute is allowed. ", "More text."])
    sentences, done = run(p, "how much leakage is okay")
    assert "Leakage is fine." in sentences
    assert not any("120" in s for s in sentences)
    assert done["escalate"] is True and done["reason"] == "ungrounded_number"


def test_out_of_scope_refused_before_llm():
    called = []

    def llm(messages):
        called.append(1)
        yield "should not run"

    p = make_pipeline(llm=llm, min_score=0.9)
    _, done = run(p, "what is the capital of France")
    assert done["reason"] == "low_retrieval_confidence" and done["escalate"] and not called


def test_emergency_short_circuits():
    p = make_pipeline(["unused"])
    sentences, done = run(p, "there is a fire at the pump")
    assert "emergency number" in sentences[0] and done["reason"] == "emergency_keyword"


def test_llm_retry_then_success():
    attempts = []

    def flaky(messages):
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("ollama restarting")
        yield "Impeller diameters are rarely reduced below 70% of their original size."

    p = make_pipeline(llm=flaky)
    sentences, done = run(p, "how far can I trim the impeller")
    assert len(attempts) == 2 and done["reason"] == "ok" and "70%" in sentences[0]


def test_llm_down_escalates_after_retries():
    def down(messages):
        raise ConnectionError("refused")
        yield  # pragma: no cover

    p = make_pipeline(llm=down)
    _, done = run(p, "how far can I trim the impeller")
    assert done["reason"] == "llm_unavailable" and done["escalate"]


def test_model_escalate_token():
    p = make_pipeline(["ESCALATE"])
    _, done = run(p, "how much leakage is okay")
    assert done["reason"] == "model_escalated" and done["escalate"]


def test_metrics_snapshot_counts_outcomes():
    p = make_pipeline(["Allowable leakage is 2 to 60 drops per minute."])
    run(p, "how much leakage is okay")
    snap = observability.METRICS.snapshot()
    assert snap["counters"]["outcome.answer"] >= 1
    assert "retrieve" in snap["latency_ms"]
    assert "fieldmind_events_total" in observability.METRICS.prometheus()
