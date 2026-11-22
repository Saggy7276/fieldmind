"""
Export the RAG index for the browser build (GitHub Pages).

    python build_index.py                 # if the index changed
    python deploy/export_web_index.py     # writes fieldmind-ui/public/data/

Writes
  chunks.json      ids, texts and on-screen citations, in index order
  embeddings.bin   float32 little-endian, n_chunks x dim, L2-normalised
The browser embeds questions with the same MiniLM model (transformers.js), so
cosine scores and the refusal thresholds match the Python server.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import chromadb
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.pipeline import PipelineConfig, RERANK_MODEL  # noqa: E402
from rag.retriever import Hit  # noqa: E402

OUT = ROOT / "fieldmind-ui" / "public" / "data"


def main() -> None:
    col = chromadb.PersistentClient(path=str(ROOT / "rag_db")).get_collection("about")
    data = col.get(include=["documents", "metadatas", "embeddings"])
    emb = np.asarray(data["embeddings"], dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12
    cfg = PipelineConfig(system_prompt="")
    chunks = [
        {"id": i, "text": t, "cite": Hit(i, t, m or {}, 0, 0, 0).citation}
        for i, t, m in zip(data["ids"], data["documents"], data["metadatas"])
    ]
    meta = {
        "built_at": (col.metadata or {}).get("built_at"),
        "embed_model": (col.metadata or {}).get("embed_model", "all-MiniLM-L6-v2"),
        "rerank_model": RERANK_MODEL,
        "dim": int(emb.shape[1]),
        "min_score": cfg.min_score,
        "keyword_floor": cfg.keyword_floor,
        "top_k": cfg.extract_top_k,
        "candidates": cfg.rerank_candidates,
        "max_picks": cfg.extract_max_picks,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chunks.json").write_text(json.dumps({"meta": meta, "chunks": chunks}, ensure_ascii=False),
                                     encoding="utf-8")
    emb.astype("<f4").tofile(OUT / "embeddings.bin")
    print(f"exported {len(chunks)} chunks x {emb.shape[1]} -> {OUT}")


if __name__ == "__main__":
    main()
