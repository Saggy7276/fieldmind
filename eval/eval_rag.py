"""
Offline retrieval benchmark for FieldMind.

    python -m eval.eval_rag                    # all strategies x {dense, hybrid}
    python -m eval.eval_rag --strategies section recursive --modes hybrid
    python -m eval.eval_rag --json eval/results.json

Reports, per chunking strategy and retrieval mode:
  hit@1 / hit@3   share of questions with a relevant chunk in the top 1 / 3
  MRR@3           mean reciprocal rank of the first relevant chunk
  chunks, avg/max words, truncated%   (chunks longer than the embedder's
                  256-token window lose their tail when embedded)
  ctx words       words actually handed to the LLM for top-3 (latency proxy)
and, for the default configuration, the best-match score distribution for
in-scope vs out-of-scope questions, used to set the refusal threshold.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from rag.chunking import STRATEGIES, chunk_document, load_documents
from rag.retriever import Retriever

ROOT = Path(__file__).resolve().parent.parent


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def relevant(text: str, phrases: list[str]) -> bool:
    t = norm(text)
    return all(norm(p) in t for p in phrases)


def parse_strategy(spec: str) -> tuple[str, str, dict]:
    """'section' or 'section:crumb_levels=99,max_words=200' -> (label, name, params)."""
    name, _, rest = spec.partition(":")
    params = {}
    for kv in filter(None, rest.split(",")):
        k, v = kv.split("=")
        params[k] = float(v) if "." in v else int(v)
    return spec, name, params


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", nargs="+", default=[str(ROOT / "about_me.txt"), str(ROOT / "knowledge_base")])
    ap.add_argument("--questions", default=str(ROOT / "eval" / "questions.json"))
    ap.add_argument("--strategies", nargs="+", default=list(STRATEGIES))
    ap.add_argument("--modes", nargs="+", default=["dense", "hybrid"])
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--bm25-weights", nargs="+", type=float, default=[1.0],
                    help="RRF weight(s) of the BM25 list in hybrid mode")
    ap.add_argument("--json", help="write results to this file")
    args = ap.parse_args()

    qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    in_scope, out_scope = qs["in_scope"], qs["out_of_scope"]
    docs = load_documents(args.docs)
    corpus = norm(" ".join(t for _, t in docs))
    missing = [q["q"] for q in in_scope if not relevant(corpus, q["must_contain"])]
    if missing:
        raise SystemExit(f"must_contain phrases not found in corpus for: {missing}")

    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    tok_limit = embedder.max_seq_length
    q_texts = [q["q"] for q in in_scope]

    rows = []
    for spec in args.strategies:
        strategy, name, params = parse_strategy(spec)
        t0 = time.perf_counter()
        chunks = [c for src, text in docs
                  for c in chunk_document(text, src, name, embed_fn=embedder.encode, **params)]
        texts = [c.text for c in chunks]
        emb = embedder.encode(texts, normalize_embeddings=True, batch_size=64)
        build_s = time.perf_counter() - t0
        n_tokens = [len(embedder.tokenizer(t, add_special_tokens=True)["input_ids"]) for t in texts]
        truncated = 100 * float(np.mean([n > tok_limit for n in n_tokens]))
        words = [c.words for c in chunks]

        configs = [(m, w) for m in args.modes for w in (args.bm25_weights if m == "hybrid" else [None])]
        for mode, w in configs:
            r = Retriever([c.id for c in chunks], texts, [c.metadata() for c in chunks], emb,
                          lambda q: embedder.encode(q, normalize_embeddings=True), mode=mode,
                          bm25_weight=w or 1.0)
            label = mode if w is None or len(args.bm25_weights) == 1 else f"{mode} w={w:g}"
            ranks, ctx_words = [], []
            for q in in_scope:
                res = r.search(q["q"], top_k=args.k)
                rank = next((i + 1 for i, h in enumerate(res.hits) if relevant(h.text, q["must_contain"])), None)
                ranks.append(rank)
                ctx_words.append(sum(len(h.text.split()) for h in res.hits))
            n = len(ranks)
            row = {
                "strategy": strategy, "mode": label,
                "hit@1": sum(r == 1 for r in ranks) / n,
                f"hit@{args.k}": sum(r is not None for r in ranks) / n,
                f"mrr@{args.k}": sum(1 / r for r in ranks if r) / n,
                "chunks": len(chunks), "avg_words": float(np.mean(words)), "max_words": int(max(words)),
                "truncated_pct": float(truncated), "ctx_words": float(np.mean(ctx_words)),
                "build_s": round(build_s, 1),
                "misses": [q for q, r in zip(q_texts, ranks) if r is None],
            }
            rows.append(row)
            print(f"  {strategy:9s} {label:6s} hit@1={row['hit@1']:.2f} hit@{args.k}={row[f'hit@{args.k}']:.2f}",
                  file=sys.stderr)

    k = args.k
    print(f"\n| strategy | retrieval | hit@1 | hit@{k} | MRR@{k} | chunks | avg words | max words | truncated | ctx words (top-{k}) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['strategy']} | {r['mode']} | {r['hit@1']:.2f} | {r[f'hit@{k}']:.2f} | {r[f'mrr@{k}']:.2f} | "
              f"{r['chunks']} | {r['avg_words']:.0f} | {r['max_words']} | {r['truncated_pct']:.0f}% | {r['ctx_words']:.0f} |")
    print("\nMisses (no relevant chunk in top-k):")
    for r in rows:
        if r["misses"]:
            print(f"  {r['strategy']}/{r['mode']}: {r['misses']}")

    # ── refusal threshold: best dense score for in-scope vs out-of-scope ──
    threshold_report = None
    if "section" in args.strategies:
        chunks = [c for src, text in docs for c in chunk_document(text, src, "section")]
        emb = embedder.encode([c.text for c in chunks], normalize_embeddings=True, batch_size=64)
        top = lambda qs_: [float((emb @ embedder.encode(q, normalize_embeddings=True)).max()) for q in qs_]
        ins, outs = top(q_texts), top(out_scope)
        print("\nBest-match cosine (section chunks):")
        print(f"  in-scope     min={min(ins):.3f}  p10={np.percentile(ins, 10):.3f}  median={np.median(ins):.3f}")
        print(f"  out-of-scope max={max(outs):.3f}  p90={np.percentile(outs, 90):.3f}  median={np.median(outs):.3f}")
        sweep = []
        for th in np.arange(0.20, 0.61, 0.025):
            false_refusals = int(sum(s < th for s in ins))
            false_accepts = int(sum(s >= th for s in outs))
            sweep.append({"threshold": round(float(th), 3), "false_refusals": false_refusals, "false_accepts": false_accepts})
        print("  threshold | in-scope refused | out-of-scope answered")
        for s in sweep:
            print(f"  {s['threshold']:.3f}     | {s['false_refusals']:2d}/{len(ins)}            | {s['false_accepts']:2d}/{len(outs)}")
        threshold_report = {"in_scope": ins, "out_of_scope": dict(zip(out_scope, outs)), "sweep": sweep}

    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows, "threshold": threshold_report}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
