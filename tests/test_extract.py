"""Extractive mode: the LLM only picks a sentence number; the manual's sentence is spoken."""

import numpy as np
import pytest

from rag import extract as ex
from rag import observability
from rag.retriever import Hit
from tests.test_pipeline import make_pipeline, run


@pytest.fixture(autouse=True)
def tmp_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(observability, "LOG_DIR", tmp_path)


def hit(text, id_="c0"):
    return Hit(id_, text, {"section": "Doc > Ch (p. 1) > Sec"}, 0.5, 1.0, 0.03)


@pytest.mark.parametrize("out, want", [
    ("3", [2]), ("[3]", [2]), ("Sentence 3, 5", [2, 4]), ("3, 3, 4", [2, 3]),
    ("0", []), ("none of them", []), ("9", []), ("2, 4, 5", [1, 3]),
    ("4\nAlso 1 is relevant", [3]),
])
def test_parse_picks(out, want):
    assert ex.parse_picks(out, n=8) == want


def test_short_followup_is_glued_to_previous_sentence():
    body = ("A major drawback of bypass valves is their detrimental impact on system efficiency. "
            "The power used to pump the bypassed fluid is wasted.")
    assert ex._units(body) == [body]


def test_anaphor_sentence_carries_its_antecedent():
    body = ("Internal recirculation occurs at low flow rates when fluid leaving the impeller forms vortices. "
            "This damages pumps in much the same way that cavitation does over a long period.")
    assert len(ex._units(body)) == 1


def test_list_items_stand_alone_and_lead_in_is_a_fragment():
    body = ("End users should consider trimming an impeller when any of the following conditions occur:\n"
            "- Many system bypass valves are open\n- Mechanical Seals. Check for leakage.\nTrimming is cheap.")
    units = ex._units(body)
    assert units[1:] == ["Many system bypass valves are open.", "Mechanical Seals. Check for leakage.",
                         "Trimming is cheap."]
    assert ex.is_fragment(units[0])


@pytest.mark.parametrize("unit, frag", [
    ("(AOR) defines the precise limits for minimum and maximum flow in a pump.", True),
    ("caused by pipe strain on the pump casing.", True),
    ("Many problems are caused by pipe Figure 8. Flow Straighteners Flow straightener (turning vanes)", True),
    ("Suction piping should be properly supported (see Figure 9).", False),
    ("affinity laws – A set of relationships that tie together pump performance characteristics.", False),
])
def test_fragments(unit, frag):
    assert ex.is_fragment(unit) is frag


def test_glossary_run_is_split_per_entry():
    body = ("VFDs are the most common type of adjustable speed drives. velocity head – The component of "
            "the total head due to motion. viscosity – The resistance of a fluid to flow.")
    assert ex._split(body)[0] == "VFDs are the most common type of adjustable speed drives."
    assert ex._split(body)[1].startswith("velocity head – ")


def test_speakable_drops_leading_connective():
    assert ex.speakable("Consequently, starting a pump deadheaded reduces stress.") == \
        "Starting a pump deadheaded reduces stress."


def test_cut_off_last_sentence_is_not_a_candidate():
    h = hit("[Sec]\nPumps move fluid from one place to another place. ASDs are usually the most efficient options in systems that are")
    cands = ex.candidate_sentences("which options are efficient", [h], lambda xs: np.ones((len(xs), 3)))
    assert [c.text for c in cands] == ["Pumps move fluid from one place to another place."]


def test_extractive_speaks_manual_sentence_verbatim():
    seen = []

    def picker(messages):
        seen.append(messages[-1]["content"])
        yield "1"

    p = make_pipeline(llm=picker, mode="extractive")
    sentences, done = run(p, "how far can I trim the impeller")
    assert sentences == ["Impeller diameters are rarely reduced below 70% of their original size."]
    assert done["reason"] == "ok" and done["sources"][0].startswith("Impeller Trimming")
    assert "[1]" in seen[0] and "Question: how far can I trim the impeller" in seen[0]


def test_reranker_selects_without_calling_llm():
    called = []

    def llm(messages):
        called.append(1)
        yield "1"

    def reranker(q, texts):  # favours the sentence mentioning 70%
        return [5.0 if "70%" in t else 0.0 for t in texts]

    p = make_pipeline(llm=llm, mode="extractive")
    p.reranker = reranker
    sentences, done = run(p, "how far can I trim the impeller")
    assert sentences[0] == "Impeller diameters are rarely reduced below 70% of their original size."
    assert done["reason"] == "ok" and not called


def test_second_sentence_only_when_close_in_score():
    cands = [ex.Candidate(t, hit(t), i) for i, t in enumerate(["a b c d e", "f g h i j", "k l m n o"])]
    close = lambda q, t: [5.0, 4.5, 1.0]
    far = lambda q, t: [5.0, 2.0, 1.0]
    assert ex.rerank_picks("q", cands, close)[0] == [0, 1]
    assert ex.rerank_picks("q", cands, far)[0] == [0]


def test_repeated_manual_text_is_read_once():
    a = "Packing. Check for leakage and adjust it. Allowable leakage is usually 2 to 60 drops per minute."
    b = "Packing. Check for leakage around the packing and adjust it. Allowable leakage is usually between 2 and 60 drops per minute."
    cands = [ex.Candidate(t, hit(t, str(i)), 0) for i, t in enumerate([a, b, "Bearings need grease twice a year here."])]
    picks, _ = ex.rerank_picks("q", cands, lambda q, t: [5.0, 4.9, 4.5])
    assert picks == [0, 2]


def test_fact_before_a_lead_in_is_kept():
    body = ("Bearings should be lubricated semiannually or annually. "
            "Operators should pay particular attention to the following:\n- Add grease.")
    units = ex._units(body)
    assert units[0] == "Bearings should be lubricated semiannually or annually."
    assert ex.is_fragment(units[1])


def test_formula_tail_is_not_read_aloud():
    s = "The affinity laws provide a relationship between impeller size and output: Q2 = D2 Q1 D1 H2 = [ D2 ] 2"
    assert ex.speakable(s) == "The affinity laws provide a relationship between impeller size and output."


def test_figure_labels_are_not_candidates():
    assert ex.noise_ratio("Flow (gpm) Head (ft) 0 50 100 150 200 250 System Curve") > ex.MAX_NOISE
    assert ex.noise_ratio("Allowable leakage is usually between 2 and 60 drops per minute.") < ex.MAX_NOISE


def test_extractive_model_says_none_escalates():
    p = make_pipeline(["0"], mode="extractive")
    sentences, done = run(p, "how far can I trim the impeller")
    assert done["reason"] == "no_answer_sentence" and done["escalate"]


def test_extractive_stops_reading_a_rambling_model():
    pieces = []

    def rambler(messages):
        for tok in ["1", "\n", "Because the impeller ", "is the most relevant ", "sentence ..."]:
            pieces.append(tok)
            yield tok

    p = make_pipeline(llm=rambler, mode="extractive")
    _, done = run(p, "how far can I trim the impeller")
    assert done["reason"] == "ok" and len(pieces) < 5


def test_extractive_retries_when_llm_down():
    def down(messages):
        raise ConnectionError("refused")
        yield  # pragma: no cover

    _, done = run(make_pipeline(llm=down, mode="extractive"), "how far can I trim the impeller")
    assert done["reason"] == "llm_unavailable"
