"""
Extractive answers: FieldMind reads out the manual's own sentence instead of
letting the LLM paraphrase it.

Why: on eval/questions.json the 7B model, when it wrote its own answer,
inverted a fact ("starting deadheaded causes motor stress" - the manual says it
reduces it) and lifted "2%" from a worked example as the trimming limit (the
manual says 70%). A sentence copied from the manual cannot do either.

    candidates = candidate_sentences(question, hits, embed_batch)   # shortlist
    picks      = rerank_picks(question, candidates, reranker)       # default selector
    # or: LLM picks a number
    messages   = selection_messages(question, candidates)
    picks      = parse_picks(llm_output, len(candidates))

Selector, measured on eval/questions.json (key fact in the spoken answer):
  cross-encoder ms-marco-MiniLM-L-6-v2, top 2 sentences   20/23, ~0.4 s on CPU
  Mistral-7B picking a sentence number                     2/5 on a spot check, ~6-15 s
  (generative answers, for comparison                     19/23 with 2 contradictions, ~20 s)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

from rag.chunking import split_sentences
from rag.retriever import Hit, rrf, tokenize

SELECTION_PROMPT = (
    "You pick the sentence from an equipment manual that answers a field operator's question. "
    "The operator will hear that sentence read out exactly as written. "
    "Reply with the number of the best sentence and nothing else. "
    "If a second sentence is needed to complete the answer, add its number after a comma. "
    "The sentences were already found by a search, so one of them usually answers the question, "
    "even when it uses different words than the question. Reply 0 only if none of them is about "
    "what was asked.\n\n"
    "Example:\n"
    "Question: how hot can the gearbox oil get\n"
    "Sentences:\n"
    "[1] Gearbox oil should be replaced every 2,000 operating hours.\n"
    "[2] Oil temperature in the gearbox must not exceed 80 degrees.\n"
    "[3] Gearboxes transmit power from the motor to the pump.\n"
    "Reply: 2"
)

Reranker = Callable[[str, list[str]], Sequence[float]]   # (question, passages) -> relevance scores

MIN_WORDS = 5          # shorter units are headings, figure labels, fragments
MAX_NOISE = 0.4        # share of non-word tokens above which text is a figure/formula, not prose
_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’-]+[.,;:!?)]*$")
MERGE_BELOW = 12       # a sentence this short is glued to the one before it
_CONNECTIVE_RE = re.compile(
    r"^(consequently|however|therefore|thus|in addition|additionally|also|similarly|"
    r"for example|in general|as a result|accordingly)\s*,\s*", re.I)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_END_RE = re.compile(r"[.!?:;)\"'”]$")
_GLOSSARY_RE = re.compile(r"^[a-z][\w\s()/,-]{0,60} [–—-] [A-Z]")   # "affinity laws – A set of ..."
_GLOSSARY_SPLIT_RE = re.compile(r"(?<=[.)])\s+(?=[a-z][\w\s()/,-]{0,60} [–—] [A-Z])")
_CAPTION_RE = re.compile(r"(?<!see )(?<!See )\bFigure \d+\.(?!\d)")
_ANAPHOR_RE = re.compile(r"^(this|these|that|those|it|they|such)\b", re.I)


@dataclass
class Candidate:
    text: str          # what is spoken
    hit: Hit           # the chunk it came from (for the citation)
    position: int      # index of the sentence inside its chunk


def _body_and_crumb(text: str) -> tuple[str, str]:
    if text.startswith("[") and "\n" in text:
        crumb, body = text.split("\n", 1)
        return body, crumb.strip("[]")
    return text, ""


def _units(body: str) -> list[str]:
    """Sentences, with a short follow-up glued to the sentence before it
    ("A major drawback of bypass valves is ... efficiency. The power used to
    pump the bypassed fluid is wasted."), and a sentence that starts with
    'This/It/They...' carrying the sentence it refers to."""
    units: list[str] = []
    after_list = False
    for s in _split(body):
        s = s.strip()
        if _LIST_ITEM_RE.match(s):
            # each checklist item stands alone ("Mechanical Seals. Check for leakage. ... replace the seal")
            item = _LIST_ITEM_RE.sub("", s).rstrip(";, ")
            units.append(item if item[-1:] in ".!?" else item + ".")
            after_list = True
            continue
        complete = bool(_END_RE.search(s)) and not s.endswith(":")  # a lead-in stays its own unit
        if (units and complete and not after_list and units[-1][-1:] in ".!?"
                and (len(s.split()) < MERGE_BELOW or _ANAPHOR_RE.match(s))):
            units[-1] += " " + s
        else:
            units.append(s)
        after_list = False
    return units


def _split(body: str) -> list[str]:
    """split_sentences, plus glossary runs ('... head). velocity head – The component ...')
    broken at each 'term – definition'."""
    out: list[str] = []
    for s in split_sentences(body):
        out.extend(p for p in _GLOSSARY_SPLIT_RE.split(s) if p.strip())
    return out


def is_fragment(unit: str) -> bool:
    """Not something to read aloud on its own: a lead-in ending in ':', a piece
    starting mid-sentence ('(AOR) defines ...'), or text with a figure caption
    pasted in by the PDF conversion ('... caused by pipe Figure 8. Flow Straighteners')."""
    u = unit.strip()
    if u.endswith(":") or u.startswith("("):
        return True
    if noise_ratio(" ".join(u.split()[:8])) > MAX_NOISE:  # starts with figure axes: 'Flow (gpm) Head (ft) 0 50'
        return True
    if u[:1].islower() and not _GLOSSARY_RE.match(u):
        return True
    return bool(_CAPTION_RE.search(u))


def noise_ratio(text: str) -> float:
    """Share of tokens that are not words: figure axes ('Flow (gpm) 0 50 100'), formulas ('Q2 = D2 Q1')."""
    toks = text.split()
    return sum(not _WORD_RE.match(t) for t in toks) / len(toks) if toks else 1.0


def speakable(sentence: str) -> str:
    """Drop a leading 'Consequently, ' etc. (it refers to text the operator never
    heard) and a trailing formula after a colon, which cannot be read aloud."""
    s = _CONNECTIVE_RE.sub("", sentence.strip())
    head, colon, tail = s.rpartition(":")
    if colon and head and noise_ratio(tail) > MAX_NOISE:
        s = head.rstrip() + "."
    return s[:1].upper() + s[1:] if s else s


def candidate_sentences(
    question: str,
    hits: Sequence[Hit],
    embed_batch: Callable[[list[str]], np.ndarray],
    n: int = 8,
) -> list[Candidate]:
    """Rank every sentence of the retrieved chunks against the question (dense
    cosine of crumb + sentence, fused by RRF with query-term overlap) and keep the best n."""
    cands: list[Candidate] = []
    keys: list[str] = []
    seen: set[str] = set()
    for h in hits:
        body, crumb = _body_and_crumb(h.text)
        units = _units(body)
        for pos, u in enumerate(units):
            if (len(u.split()) < MIN_WORDS or u in seen or is_fragment(u)
                    or noise_ratio(speakable(u)) > MAX_NOISE):
                continue
            if pos == len(units) - 1 and not _END_RE.search(u):
                continue  # chunk boundary cut this sentence off

            seen.add(u)
            cands.append(Candidate(u, h, pos))
            keys.append(f"{crumb} {u}".strip())
    if not cands:
        return []
    qv = np.asarray(embed_batch([question]), dtype=np.float32)[0]
    sv = np.asarray(embed_batch(keys), dtype=np.float32)
    dense = (sv @ qv) / (np.linalg.norm(sv, axis=1) * np.linalg.norm(qv) + 1e-12)
    terms = set(tokenize(question))
    overlap = np.array([len(terms & set(tokenize(k))) for k in keys], dtype=np.float32)
    fused = rrf([list(np.argsort(-dense)), list(np.argsort(-overlap, kind="stable"))])
    order = sorted(fused, key=fused.get, reverse=True)[:n]
    return [cands[i] for i in order]


def rerank_picks(question: str, candidates: Sequence[Candidate], reranker: Reranker,
                 max_picks: int = 2, max_gap: float = 1.0) -> tuple[list[int], list[float]]:
    """Score each candidate with a cross-encoder (section heading prepended for
    context). Further sentences are only added when they score within max_gap of
    the best one: on eval/questions.json a gap of 1.0 keeps the same 20/23 key-fact
    rate as always reading two, but adds a second sentence to 9 answers instead of 23."""
    texts = [f"{_body_and_crumb(c.hit.text)[1].split(' > ')[-1]}: {c.text}".lstrip(": ") for c in candidates]
    scores = [float(s) for s in reranker(question, texts)]
    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
    picks: list[int] = []
    for i in order:
        if len(picks) == max_picks or scores[order[0]] - scores[i] >= max_gap:
            break
        # the manual repeats some text (the maintenance checklist appears twice): don't read it twice
        if not any(_similar(candidates[i].text, candidates[j].text) for j in picks):
            picks.append(i)
    return picks, scores


def _similar(a: str, b: str, threshold: float = 0.7) -> bool:
    """Most of the shorter text's words also occur in the longer one."""
    ta, tb = set(tokenize(a)), set(tokenize(b))
    return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= threshold


def selection_messages(question: str, candidates: Sequence[Candidate]) -> list[dict]:
    listing = "\n".join(f"[{i}] {c.text}" for i, c in enumerate(candidates, 1))
    return [
        {"role": "system", "content": SELECTION_PROMPT},
        {"role": "user", "content": f"Question: {question}\nSentences:\n{listing}\nReply:"},
    ]


def parse_picks(output: str, n: int, max_picks: int = 2) -> list[int]:
    """'3' / '[3]' / 'Sentence 3, 5' -> 0-based indices; [] means 'none answers'.
    Only the first line counts, so a rambling model can't add picks."""
    first = next((line for line in output.strip().splitlines() if line.strip()), "")
    first = re.sub(r"^\s*reply\s*:", "", first, flags=re.I)
    picks: list[int] = []
    for m in re.findall(r"\d+", first):
        i = int(m)
        if i == 0:
            break
        if 1 <= i <= n and i - 1 not in picks:
            picks.append(i - 1)
        if len(picks) == max_picks:
            break
    return picks


def order_picks(picks: list[int], candidates: Sequence[Candidate]) -> list[Candidate]:
    """Best first, except two sentences from the same chunk are read in manual order."""
    chosen = [candidates[i] for i in picks]
    if len(chosen) == 2 and chosen[0].hit.id == chosen[1].hit.id:
        chosen.sort(key=lambda c: c.position)
    return chosen
