"""
End-to-end run of eval/questions.json through the real pipeline and the real
Ollama model (same config as the server, no audio).

    python -m eval.e2e                       # all questions
    python -m eval.e2e --limit 5             # quick check
    python -m eval.e2e --out eval/e2e_results.md

For each in-scope question it reports the outcome, whether the answer contains
the expected phrase, time to first sentence and total time. Out-of-scope
questions must end in an escalation. Traces go to logs/traces.jsonl as usual.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import chromadb
import ollama
from sentence_transformers import CrossEncoder, SentenceTransformer

from rag.pipeline import DEFAULT_SYSTEM_PROMPT, RERANK_MODEL, FieldMindPipeline, PipelineConfig
from rag.retriever import Retriever

ROOT = Path(__file__).resolve().parent.parent


def norm(s: str) -> str:
    return " ".join(s.lower().split())


def grade(answer: str, case: dict) -> tuple[bool, bool, bool]:
    """-> (strict, fact, contradicted).
    strict: the manual's key sentence appears verbatim (the old metric; punishes paraphrase).
    fact:   every answer_facts group is matched by one alternative and no must_not phrase occurs."""
    a = norm(answer)
    strict = norm(case["must_contain"][-1]) in a
    contradicted = any(norm(p) in a for p in case.get("must_not", []))
    groups = case.get("answer_facts") or [[case["must_contain"][-1]]]
    fact = all(any(norm(alt) in a for alt in g) for g in groups) and not contradicted
    return strict, fact, contradicted


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="fieldmind")
    ap.add_argument("--out", default=str(ROOT / "eval" / "e2e_results.md"))
    ap.add_argument("--only", default="", help="comma-separated 1-based question numbers")
    ap.add_argument("--mode", choices=["extractive", "generative"], default="extractive")
    ap.add_argument("--selector", choices=["reranker", "llm"], default="reranker",
                    help="extractive mode: who picks the sentence")
    args = ap.parse_args()

    qs = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    cases = [(q["q"], q, True) for q in qs["in_scope"]] + [(q, {}, False) for q in qs["out_of_scope"]]
    if args.only:
        keep = {int(x) for x in args.only.split(",")}
        cases = [c for i, c in enumerate(cases, 1) if i in keep]
    if args.limit:
        cases = cases[: args.limit]

    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    col = chromadb.PersistentClient(path=str(ROOT / "rag_db")).get_collection("about")
    client = ollama.Client(timeout=120)

    def llm(messages):
        for chunk in client.chat(model=args.model, messages=messages, stream=True,
                                 options={"temperature": 0.1, "num_predict": 200}):
            yield chunk["message"]["content"]

    reranker = None
    if args.mode == "extractive" and args.selector == "reranker":
        ce = CrossEncoder(RERANK_MODEL)
        reranker = lambda q, texts: ce.predict([(q, t) for t in texts])
    pipe = FieldMindPipeline(Retriever.from_chroma(col, embedder), llm,
                             PipelineConfig(system_prompt=DEFAULT_SYSTEM_PROMPT, mode=args.mode), reranker)

    rows = []
    for i, (q, case, in_scope) in enumerate(cases, 1):
        t0 = time.perf_counter()
        first = None
        sentences, done = [], {}
        for ev in pipe.run(q, channel="e2e"):
            if ev["type"] == "sentence":
                first = first or time.perf_counter() - t0
                sentences.append(ev["text"])
            else:
                done = ev
        total = time.perf_counter() - t0
        answer = " ".join(sentences)
        strict = contradicted = False
        if in_scope:
            ok = done.get("reason") == "ok"
            strict, fact, contradicted = grade(answer, case) if ok else (False, False, False)
            correct = ok and fact
        else:
            correct = bool(done.get("escalate"))
        rows.append({"q": q, "in_scope": in_scope, "reason": done.get("reason"), "correct": correct,
                     "strict": strict, "contradicted": contradicted,
                     "first_s": round(first or 0, 1), "total_s": round(total, 1), "answer": answer,
                     "sources": done.get("sources", [])[:1]})
        print(f"[{i}/{len(cases)}] {done.get('reason'):26s} {total:5.1f}s  {q}\n      → {answer[:200]}", flush=True)

    ins = [r for r in rows if r["in_scope"]]
    outs = [r for r in rows if not r["in_scope"]]
    answered = [r for r in ins if r["reason"] == "ok"]
    lines = ["# FieldMind end-to-end run", "",
             f"Model `{args.model}`, mode `{args.mode}`"
             f"{f', selector `{args.selector}`' if args.mode == 'extractive' else ''}, {len(ins)} in-scope + {len(outs)} out-of-scope questions.", ""]
    if ins:
        reasons = {}
        for r in ins:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        lines += [f"- In-scope answered: {len(answered)}/{len(ins)}; reasons: {reasons}",
                  f"- In-scope answers with the key fact: {sum(r['correct'] for r in ins)}/{len(ins)}",
                  f"- In-scope answers quoting the manual sentence verbatim (old metric): "
                  f"{sum(r['strict'] for r in ins)}/{len(ins)}",
                  f"- Answers contradicting the manual: {sum(r['contradicted'] for r in ins)}"]
    if answered:
        firsts = sorted(r["first_s"] for r in answered)
        totals = sorted(r["total_s"] for r in answered)
        lines += [f"- Answered: time to first sentence median {firsts[len(firsts)//2]} s, "
                  f"max {firsts[-1]} s; total median {totals[len(totals)//2]} s, max {totals[-1]} s"]
    if outs:
        lines += [f"- Out-of-scope escalated: {sum(r['correct'] for r in outs)}/{len(outs)}"]
    lines += ["", "| # | question | outcome | expected fact | first sentence s | total s | answer |",
              "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        if r["in_scope"]:
            fact = "CONTRADICTS" if r["contradicted"] else ("yes" if r["correct"] else "no")
        else:
            fact = "escalated" if r["correct"] else "ANSWERED"
        ans = r["answer"].replace("|", "/")[:220]
        lines.append(f"| {i} | {r['q']} | {r['reason']} | {fact} | {r['first_s']} | {r['total_s']} | {ans} |")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines[:11]))


if __name__ == "__main__":
    main()
