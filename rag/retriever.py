"""
Hybrid retrieval for FieldMind: dense (MiniLM cosine) + BM25 keyword search,
fused with Reciprocal Rank Fusion (RRF).

Why hybrid: operators ask about exact tokens — tag numbers, abbreviations,
model codes ("NPSHA", "VFD", "V-101B"). A small sentence-embedding model
blurs those together; BM25 matches them exactly. RRF combines the two rank
lists without having to calibrate their very different score scales.

The index is small (hundreds to a few thousand chunks), so everything is held
in memory as a numpy matrix; Chroma is only the on-disk store.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-./][a-z0-9]+)*")
_STOPWORDS = set(
    "a an and are as at be by can do does for from how i if in is it its me my of on or "
    "should so that the their there these this to was what when where which who why will "
    "with you your we our".split()
)


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens; keeps tags like 'v-101b' and '3.5' whole."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class BM25:
    """Okapi BM25 over pre-tokenised documents."""

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = np.array([sum(tf.values()) for tf in self.tfs], dtype=np.float32)
        self.avg_len = float(self.lens.mean()) if len(docs) else 0.0
        df = Counter(t for tf in self.tfs for t in tf)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(len(self.tfs), dtype=np.float32)
        norm = self.k1 * (1 - self.b + self.b * self.lens / (self.avg_len or 1.0))
        for term in set(tokenize(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            tf = np.array([d.get(term, 0) for d in self.tfs], dtype=np.float32)
            out += idf * tf * (self.k1 + 1) / (tf + norm)
        return out


def rrf(rankings: Sequence[Sequence[int]], k: int = 60, weights: Sequence[float] | None = None) -> dict[int, float]:
    """Weighted Reciprocal Rank Fusion: score(d) = sum_i w_i / (k + rank_i(d))."""
    weights = weights or [1.0] * len(rankings)
    fused: dict[int, float] = {}
    for ranking, w in zip(rankings, weights):
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + w / (k + rank + 1)
    return fused


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    dense: float
    bm25: float
    score: float

    @property
    def citation(self) -> str:
        """'<document> > <chapter (pages)> > <sub-section>' — short enough to show on screen."""
        path = (self.metadata.get("section") or "").split(" > ")
        if not path[0]:
            return self.metadata.get("source", self.id)
        return " > ".join(path if len(path) <= 3 else [path[0], *path[-2:]])


@dataclass
class RetrievalResult:
    query: str
    mode: str
    hits: list[Hit] = field(default_factory=list)
    top_dense: float = 0.0  # best cosine similarity over the whole index
    # Dense and BM25 both rank the same chunk first, and that chunk contains every
    # content word of the query. Rescues short definitional questions ("what do the
    # affinity laws describe") whose cosine is low because MiniLM blurs rare terms.
    keyword_match: bool = False

    def context(self, max_words: int = 450) -> str:
        """Join hits best-first within a word budget (the top hit always fits)."""
        parts: list[str] = []
        used = 0
        for h in self.hits:
            n = len(h.text.split())
            if parts and used + n > max_words:
                continue
            parts.append(h.text)
            used += n
        return "\n\n".join(parts)

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(h.citation for h in self.hits))

    def log_view(self) -> list[dict]:
        return [
            {"id": h.id, "dense": round(h.dense, 4), "bm25": round(h.bm25, 3), "score": round(h.score, 5)}
            for h in self.hits
        ]


class Retriever:
    def __init__(
        self,
        ids: Sequence[str],
        texts: Sequence[str],
        metadatas: Sequence[dict],
        embeddings: np.ndarray,
        embed_query: Callable[[str], np.ndarray],
        mode: str = "hybrid",
        candidates: int = 20,
        bm25_weight: float = 1.0,
        embed_batch: Callable[[list[str]], np.ndarray] | None = None,
    ):
        if mode not in {"dense", "bm25", "hybrid"}:
            raise ValueError(f"unknown retrieval mode {mode!r}")
        self.ids, self.texts, self.metadatas = list(ids), list(texts), list(metadatas)
        emb = np.asarray(embeddings, dtype=np.float32)
        self.emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12)
        self.embed_query = embed_query
        self.embed_batch = embed_batch or (lambda texts: np.stack([embed_query(t) for t in texts]))
        self.mode = mode
        self.candidates = candidates
        self.bm25_weight = bm25_weight
        self.bm25 = BM25(self.texts)

    @classmethod
    def from_chroma(cls, collection, embedder, **kw) -> "Retriever":
        data = collection.get(include=["documents", "metadatas", "embeddings"])
        return cls(
            ids=data["ids"],
            texts=data["documents"],
            metadatas=data["metadatas"],
            embeddings=np.asarray(data["embeddings"]),
            embed_query=lambda q: embedder.encode(q, normalize_embeddings=True),
            embed_batch=lambda texts: embedder.encode(texts, normalize_embeddings=True, batch_size=64),
            **kw,
        )

    def __len__(self) -> int:
        return len(self.ids)

    def search(self, query: str, top_k: int = 3) -> RetrievalResult:
        q = np.asarray(self.embed_query(query), dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-12
        dense = self.emb @ q
        sparse = self.bm25.scores(query) if self.mode != "dense" else np.zeros_like(dense)

        if self.mode == "dense":
            order = list(np.argsort(-dense)[:top_k])
            scores = {i: float(dense[i]) for i in order}
        elif self.mode == "bm25":
            order = list(np.argsort(-sparse)[:top_k])
            scores = {i: float(sparse[i]) for i in order}
        else:
            c = self.candidates
            fused = rrf(
                [list(np.argsort(-dense)[:c]), [i for i in np.argsort(-sparse)[:c] if sparse[i] > 0]],
                weights=[1.0, self.bm25_weight],
            )
            order = sorted(fused, key=fused.get, reverse=True)[:top_k]
            scores = fused

        hits = [
            Hit(self.ids[i], self.texts[i], self.metadatas[i] or {}, float(dense[i]), float(sparse[i]), scores[i])
            for i in order
        ]
        keyword_match = False
        terms = set(tokenize(query))
        if self.mode == "hybrid" and len(dense) and terms and sparse.max() > 0:
            top = int(np.argmax(dense))
            keyword_match = top == int(np.argmax(sparse)) and terms <= set(self.bm25.tfs[top])
        return RetrievalResult(query, self.mode, hits, float(dense.max()) if len(dense) else 0.0, keyword_match)
