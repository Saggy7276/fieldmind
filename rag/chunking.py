"""
Document chunking strategies for the FieldMind RAG index.

Every strategy takes raw document text and returns a list of `Chunk`s. The text of
a chunk is exactly what gets embedded and what the LLM sees as context.

Strategies
----------
line       One chunk per non-empty line. The original FieldMind approach; works
           for a fact-per-line file, breaks down on real manuals.
fixed      Sliding window of N words with overlap. Simple, structure-blind.
sentence   Sliding window of N sentences with overlap.
recursive  Split on headings, then paragraphs, then lines, then sentences,
           until every piece fits the size budget.
semantic   Embed every sentence; start a new chunk where the similarity between
           neighbouring sentences drops (topic shift).
section    Structure-aware (FieldMind default). Follows the Markdown heading
           tree, keeps numbered procedures and tables together, and prefixes
           every chunk with its section path, e.g.
           "[Pump Station P-101 > 4. Startup Procedure]".

See docs/adr/0001-chunking-strategy.md for why `section` is the default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np

# all-MiniLM-L6-v2 truncates input at 256 word-piece tokens. English technical
# text averages ~1.3 word pieces per word, so ~160 words (plus a short section
# path) is the largest chunk that is embedded without being cut off.
DEFAULT_MAX_WORDS = 160

EmbedFn = Callable[[Sequence[str]], np.ndarray]


@dataclass
class Chunk:
    text: str
    source: str
    strategy: str
    index: int
    section: str = ""

    @property
    def id(self) -> str:
        return f"{Path(self.source).stem}-{self.strategy}-{self.index:04d}"

    @property
    def words(self) -> int:
        return n_words(self.text)

    def metadata(self) -> dict:
        return {
            "source": self.source,
            "strategy": self.strategy,
            "index": self.index,
            "section": self.section,
            "words": self.words,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Text helpers
# ─────────────────────────────────────────────────────────────────────────────
_SENT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"(\[])')
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_TABLE_RE = re.compile(r"^\s*\|")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def n_words(text: str) -> int:
    return len(text.split())


def _is_structural(line: str) -> bool:
    return bool(_LIST_RE.match(line) or _TABLE_RE.match(line) or _HEADING_RE.match(line.strip()))


def logical_lines(text: str) -> list[str]:
    """Re-join hard-wrapped prose into paragraphs; keep list items, table rows
    and headings as their own lines."""
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(" ".join(para))
            para.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif _is_structural(raw):
            flush()
            out.append(line)
        else:
            para.append(line.lstrip("> ").strip())
    flush()
    return out


def split_sentences(text: str) -> list[str]:
    """Sentences from prose; list items, table rows and headings stay whole."""
    units: list[str] = []
    for line in logical_lines(text):
        if _is_structural(line):
            units.append(line)
        else:
            units.extend(s.strip() for s in _SENT_RE.split(line) if s.strip())
    return units


def _windows(items: list[str], size: int, overlap: int, joiner: str) -> list[str]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than window size")
    step = size - overlap
    out = []
    for start in range(0, len(items), step):
        out.append(joiner.join(items[start:start + size]))
        if start + size >= len(items):
            break
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Strategies — each returns a list of (section, text)
# ─────────────────────────────────────────────────────────────────────────────
def line_chunks(text: str, **_) -> list[tuple[str, str]]:
    return [("", line.strip()) for line in text.splitlines() if line.strip()]


def fixed_chunks(text: str, size: int = 120, overlap: int = 20, **_) -> list[tuple[str, str]]:
    return [("", w) for w in _windows(text.split(), size, overlap, " ")]


def sentence_chunks(text: str, window: int = 4, overlap: int = 1, **_) -> list[tuple[str, str]]:
    return [("", w) for w in _windows(split_sentences(text), window, overlap, " ")]


_RECURSIVE_SEPARATORS = [
    ("\n## ", "\n"),
    ("\n### ", "\n"),
    ("\n\n", "\n\n"),
    ("\n", "\n"),
    ("<sentence>", " "),
    (" ", " "),
]


def _recursive_split(text: str, seps: list[tuple[str, str]], max_words: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if n_words(text) <= max_words:
        return [text]
    if not seps:
        words = text.split()
        return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

    (sep, joiner), rest = seps[0], seps[1:]
    if sep == "<sentence>":
        parts = _SENT_RE.split(text)
    else:
        parts = text.split(sep)
        if sep.startswith("\n#"):  # keep the heading marker on the piece it starts
            parts = [parts[0]] + [sep.lstrip("\n") + p for p in parts[1:]]
    if len(parts) == 1:
        return _recursive_split(text, rest, max_words)

    out: list[str] = []
    buf = ""
    for part in parts:
        if not part.strip():
            continue
        if n_words(part) > max_words:
            if buf:
                out.append(buf.strip())
                buf = ""
            out.extend(_recursive_split(part, rest, max_words))
            continue
        candidate = f"{buf}{joiner}{part}" if buf else part
        if n_words(candidate) <= max_words:
            buf = candidate
        else:
            out.append(buf.strip())
            buf = part
    if buf.strip():
        out.append(buf.strip())
    return out


def recursive_chunks(text: str, max_words: int = DEFAULT_MAX_WORDS, **_) -> list[tuple[str, str]]:
    return [("", c) for c in _recursive_split("\n" + text, _RECURSIVE_SEPARATORS, max_words)]


def semantic_chunks(
    text: str,
    embed_fn: EmbedFn | None = None,
    percentile: float = 80.0,
    max_words: int = DEFAULT_MAX_WORDS,
    **_,
) -> list[tuple[str, str]]:
    if embed_fn is None:
        raise ValueError("semantic chunking needs an embed_fn")
    sents = split_sentences(text)
    if len(sents) < 3:
        return [("", " ".join(sents))] if sents else []

    emb = np.asarray(embed_fn(sents), dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12
    distance = 1.0 - np.sum(emb[:-1] * emb[1:], axis=1)  # between sentence i and i+1
    threshold = float(np.percentile(distance, percentile))

    chunks: list[str] = []
    current = [sents[0]]
    for i, sent in enumerate(sents[1:]):
        topic_shift = distance[i] > threshold
        too_big = n_words(" ".join(current + [sent])) > max_words
        if topic_shift or too_big:
            chunks.append(" ".join(current))
            current = [sent]
        else:
            current.append(sent)
    chunks.append(" ".join(current))
    return [("", c) for c in chunks]


# ── section (structure-aware) ────────────────────────────────────────────────
def _parse_sections(text: str, title: str) -> list[tuple[list[str], list[str]]]:
    """Return (heading path, body lines) for every section that has a body."""
    stack: list[tuple[int, str]] = []
    sections: list[tuple[list[str], list[str]]] = []
    body: list[str] = []

    def flush() -> None:
        if any(l.strip() for l in body):
            path = [name for _, name in stack] or [title]
            sections.append((path, body.copy()))
        body.clear()

    for line in text.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            flush()
            level = len(m.group(1))
            stack = [s for s in stack if s[0] < level]
            stack.append((level, m.group(2).strip()))
        else:
            body.append(line)
    flush()
    return sections


def _blocks(lines: list[str]) -> list[list[str]]:
    """Blank-line separated blocks. A block ending in ':' (e.g. 'The isolation
    points are:') is merged with the list that follows it."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        if line.strip():
            cur.append(line.rstrip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)

    merged: list[list[str]] = []
    for b in blocks:
        if merged and merged[-1][-1].rstrip().endswith(":"):
            merged[-1] = merged[-1] + b
        else:
            merged.append(b)
    return merged


def _split_block(block: list[str], max_words: int) -> list[str]:
    """Split an oversized block. Lists and tables are split between items/rows,
    repeating the intro line or table header and overlapping by one item so a
    step is never separated from the step before it."""
    lines = logical_lines("\n".join(block))
    structured = [l for l in lines if _LIST_RE.match(l) or _TABLE_RE.match(l)]
    if len(structured) < len(lines) / 2:  # mostly prose: pack sentences
        return _recursive_split("\n".join(block), _RECURSIVE_SEPARATORS[3:], max_words)

    header: list[str] = []
    if _TABLE_RE.match(lines[0]):
        header = lines[:2]  # header row + |---| separator
    elif not _LIST_RE.match(lines[0]):
        header = lines[:1]  # intro sentence
    items = lines[len(header):]

    out: list[str] = []
    if n_words("\n".join(header)) > max_words // 3:  # long intro: emit it alone, don't repeat it
        out.extend(_recursive_split(header[0], _RECURSIVE_SEPARATORS[4:], max_words))
        header = []
    budget = max_words - n_words("\n".join(header))
    split_items: list[str] = []
    for item in items:  # a single over-long item is split by sentence
        if n_words(item) > budget:
            split_items.extend(_recursive_split(item, _RECURSIVE_SEPARATORS[4:], budget))
        else:
            split_items.append(item)

    cur: list[str] = []
    for item in split_items:
        if cur and n_words("\n".join(header + cur + [item])) > max_words:
            out.append("\n".join(header + cur))
            cur = cur[-1:]  # one-item overlap
        cur.append(item)
    if cur:
        out.append("\n".join(header + cur))
    return out


_PAGES_RE = re.compile(r"\s*\(p\. [\d\-]+\)$")


def section_chunks(
    text: str,
    title: str = "document",
    max_words: int = DEFAULT_MAX_WORDS,
    crumb_levels: int = 2,
    **_,
) -> list[tuple[str, str]]:
    """`crumb_levels` = how many of the nearest headings are written into the
    chunk text. The full path (with page numbers) is kept as metadata for
    citations; only the short form is embedded, because a long prefix shared by
    hundreds of chunks makes them look alike to the embedder."""
    out: list[tuple[str, str]] = []
    for path, body in _parse_sections(text, title):
        full_path = " > ".join(path)
        levels = int(crumb_levels)
        crumb = " > ".join(_PAGES_RE.sub("", p) for p in path[-levels:]) if levels else ""
        budget = max_words - n_words(crumb)
        pieces: list[str] = []
        buf = ""
        for block in _blocks(body):
            block_text = "\n".join(logical_lines("\n".join(block)))
            if n_words(block_text) > budget:
                if buf:
                    pieces.append(buf)
                    buf = ""
                pieces.extend(_split_block(block, budget))
                continue
            candidate = f"{buf}\n{block_text}" if buf else block_text
            if n_words(candidate) <= budget:
                buf = candidate
            else:
                pieces.append(buf)
                buf = block_text
        if buf:
            pieces.append(buf)
        out.extend((full_path, f"[{crumb}]\n{p}" if crumb else p) for p in pieces)
    return out


STRATEGIES: dict[str, Callable[..., list[tuple[str, str]]]] = {
    "line": line_chunks,
    "fixed": fixed_chunks,
    "sentence": sentence_chunks,
    "recursive": recursive_chunks,
    "semantic": semantic_chunks,
    "section": section_chunks,
}


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────
def chunk_document(
    text: str,
    source: str,
    strategy: str = "section",
    embed_fn: EmbedFn | None = None,
    **params,
) -> list[Chunk]:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {sorted(STRATEGIES)}")
    title = Path(source).stem.replace("_", " ")
    pieces = STRATEGIES[strategy](text, embed_fn=embed_fn, title=title, **params)
    return [
        Chunk(text=t, source=source, strategy=strategy, index=i, section=sec)
        for i, (sec, t) in enumerate(pieces)
        if t.strip()
    ]


def load_documents(paths: Iterable[str | Path]) -> list[tuple[str, str]]:
    """(source, text) for every .md / .txt file in the given files or folders."""
    docs: list[tuple[str, str]] = []
    for p in map(Path, paths):
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if f.is_file() and f.suffix.lower() in {".md", ".txt"}:
                docs.append((f.as_posix(), f.read_text(encoding="utf-8")))
    return docs
