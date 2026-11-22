"""
Guardrails for FieldMind. A wrong confident answer to a field operator is worse
than no answer, so every stage can stop the pipeline and escalate to a human.

  input      empty / rambling transcripts, prompt-injection attempts, and
             emergencies (which must never wait on an LLM)
  retrieval  refuse to answer when nothing in the manuals is close enough
  output     checked sentence by sentence *before* it is spoken: every number
             in the answer must appear in the retrieved context or the question
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ANSWER, REJECT, ESCALATE, EMERGENCY = "answer", "reject", "escalate", "emergency"

EMERGENCY_MESSAGE = (
    "This sounds like an emergency. Stop work, move to a safe place, "
    "and call your site emergency number now."
)
ESCALATE_MESSAGE = "I can't answer that reliably from the manuals. I'm passing this to a specialist."
INJECTION_MESSAGE = "I can only answer questions about the equipment documentation."

_EMERGENCY_RE = re.compile(
    r"\b(fire|smoke|burning smell|injur\w*|bleeding|unconscious|not breathing|"
    r"electric(?:al)? shock|electrocut\w*|gas leak|explosion|collapsed|trapped|chemical spill)\b",
    re.I,
)
_INJECTION_RE = re.compile(
    r"(ignore (all |any |the |your )?(previous |above |prior )?(instructions|rules|prompt)|"
    r"disregard (the |all |your )?(previous |above )?(instructions|rules)|"
    r"(reveal|print|show|repeat) (me )?(your|the) (system )?(prompt|instructions)|"
    r"you are now|pretend (to be|you are)|jailbreak|developer mode)",
    re.I,
)
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class Verdict:
    action: str  # answer | reject | escalate | emergency
    reason: str = "ok"
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.action == ANSWER


OK = Verdict(ANSWER)


# ── input ───────────────────────────────────────────────────────────────────
def check_input(question: str, max_words: int = 60) -> Verdict:
    q = (question or "").strip()
    if len(q) < 3:
        return Verdict(REJECT, "empty_input", "I didn't catch that. Please repeat the question.")
    if _EMERGENCY_RE.search(q):
        return Verdict(EMERGENCY, "emergency_keyword", EMERGENCY_MESSAGE)
    if _INJECTION_RE.search(q):
        return Verdict(REJECT, "prompt_injection", INJECTION_MESSAGE)
    if len(q.split()) > max_words:
        return Verdict(REJECT, "input_too_long", "Please ask one short question at a time.")
    return OK


# ── retrieval ───────────────────────────────────────────────────────────────
def check_retrieval(top_dense: float, min_score: float, keyword_match: bool = False,
                    keyword_floor: float = 0.2) -> Verdict:
    """Refuse when nothing is close enough. Below min_score a question is still
    answered if dense and keyword search agree on a chunk that contains every
    query term (see RetrievalResult.keyword_match), down to keyword_floor."""
    if top_dense >= min_score or (keyword_match and top_dense >= keyword_floor):
        return OK
    return Verdict(ESCALATE, "low_retrieval_confidence", ESCALATE_MESSAGE)


# ── output ──────────────────────────────────────────────────────────────────
# "1. Check the seal" / "2) Vent the casing": list numbering, not a fact to ground.
# Inside a released sentence, "<n>. " can only be a list marker, because a
# number that ends a sentence is followed by the sentence boundary, not a space.
_LIST_MARKER_RE = re.compile(r"(?:^|(?<=\s))\d{1,2}[.)](?=\s)")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER_RE.findall(_LIST_MARKER_RE.sub(" ", text))}


def ungrounded_numbers(sentence: str, context: str, question: str = "") -> set[str]:
    """Numbers stated in the answer that appear neither in the context nor in
    the question. In a maintenance answer these are the dangerous hallucinations:
    torque values, limits, intervals."""
    return _numbers(sentence) - _numbers(context) - _numbers(question)


def check_sentence(sentence: str, context: str, question: str = "") -> Verdict:
    if "ESCALATE" in sentence.upper():
        return Verdict(ESCALATE, "model_escalated", ESCALATE_MESSAGE)
    bad = ungrounded_numbers(sentence, context, question)
    if bad:
        return Verdict(
            ESCALATE,
            "ungrounded_number",
            "I'm not confident about the exact figure, so I'm passing this to a specialist. "
            "Please check the manual section listed on screen.",
        )
    return OK


def grounding_ratio(answer: str, context: str) -> float:
    """Share of the answer's content words (4+ letters) that occur in the context.
    Logged for monitoring, not used to block: paraphrase is legitimate."""
    words = [w for w in re.findall(r"[a-z]{4,}", answer.lower())]
    if not words:
        return 1.0
    ctx = set(re.findall(r"[a-z]{4,}", context.lower()))
    return sum(w in ctx for w in words) / len(words)
