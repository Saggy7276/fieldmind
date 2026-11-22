"""
PDF → structured Markdown, so the section-aware chunker can see the manual's
structure and every chunk can cite the page it came from.

    python -m rag.ingest knowledge_base/sources/doe_pump_sourcebook.pdf \
        --title "Improving Pumping System Performance (US DOE, 2006)" \
        --out knowledge_base/doe_pumping_sourcebook.md

What it does (all of it was needed for the DOE sourcebook):
  * section headings from the PDF bookmark outline, flattened and sorted by page,
    because the outline nests some entries under the wrong parent
  * page ranges in headings, e.g. "### Basic Pump Maintenance (p. 37-40)"
  * drops running headers/footers (lines repeated on many pages) and page numbers
  * bullet glyphs (■, •) → "- " list items, with wrapped continuation lines
    joined back onto their bullet
  * collapses tab-justified text ("A \t summary \t of"), re-joins hyphenated
    words ("main-\\ntenance"), expands ligatures (ﬁ, ﬂ)
  * lines starting with the sourcebook's heading icon (private-use glyph
    U+E075) become "####" sub-headings
"""

from __future__ import annotations

import argparse
import logging
import re
from collections import Counter
from pathlib import Path

import pypdf

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings

_BULLET_CHARS = "■•▪●◦"
_HEADING_ICON_RE = re.compile(r"^\s*\s*")
_BULLET_RE = re.compile(rf"^\s*[{_BULLET_CHARS}]\s*")
_TOP_LEVEL_RE = re.compile(r"^(Section \d|Appendi|Quick Start)", re.I)
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}
_SENT_END = (".", ":", "?", "!")
DEFAULT_SKIP = {"acknowledgements", "contents", "table of contents"}


def _norm(line: str) -> str:
    """Key used to detect running headers/footers: digits removed, spaces collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line)).strip().lower()


def _clean_line(line: str) -> str:
    for k, v in _LIGATURES.items():
        line = line.replace(k, v)
    line = line.replace("�", "'")
    return re.sub(r"[ \t]+", " ", line).rstrip()


def _flatten_outline(reader: pypdf.PdfReader) -> list[tuple[int, int, str]]:
    """(page_index, level, title) sorted by page. Level 2 = top section, 3 = sub."""
    entries: list[tuple[int, str]] = []

    def walk(items):
        for it in items:
            if isinstance(it, list):
                walk(it)
            else:
                try:
                    entries.append((reader.get_destination_page_number(it), it.title.strip()))
                except Exception:
                    pass

    walk(reader.outline)
    out: list[tuple[int, int, str]] = []
    by_page: dict[int, list[str]] = {}
    for page, title in sorted(entries, key=lambda e: e[0]):
        by_page.setdefault(page, []).append(title)
    for page, titles in sorted(by_page.items()):
        tops = [t for t in titles if _TOP_LEVEL_RE.match(t) or t.lower() in DEFAULT_SKIP]
        subs = [t for t in titles if t not in tops]
        for t in tops:
            out.append((page, 2, t))
        if subs:  # same-page fragments, e.g. "Analyze Life-Cycle Costs" + "Before Making a Decision"
            out.append((page, 3, " – ".join(dict.fromkeys(subs))))
    return out


def _page_lines(reader: pypdf.PdfReader, outline: list[tuple[int, int, str]]) -> list[list[str]]:
    """Clean lines per page, minus running headers/footers, side tabs that repeat
    a section title, and fact-sheet footers like "5. Basic Pump Maintenance"."""
    top_titles = {_norm(t) for _, level, t in outline if level == 2}
    sub_titles = {_norm(part) for _, level, t in outline if level == 3 for part in t.split(" – ")}
    pages = [[_clean_line(l) for l in (p.extract_text() or "").splitlines()] for p in reader.pages]
    counts = Counter(k for lines in pages for k in {_norm(l) for l in lines if l.strip()})
    threshold = max(3, int(0.15 * len(pages)))
    boiler = {k for k, n in counts.items() if n >= threshold}
    cleaned = []
    for lines in pages:
        keep = []
        last = len(lines) - 1
        for i, l in enumerate(lines):
            s = l.strip()
            key = _norm(s)
            if not s or key in boiler or key in top_titles or re.fullmatch(r"[ivx\d]+", s):
                continue
            if i in (0, 1, last) and _norm(re.sub(r"^\d+\.\s*", "", s)) in sub_titles:
                continue  # page header/footer naming the fact sheet
            keep.append(l)
        cleaned.append(keep)
    return cleaned


def _is_subheading(raw: str) -> bool:
    return bool(_HEADING_ICON_RE.match(raw)) and len(raw.split()) <= 12


def _page_to_markdown(lines: list[str]) -> list[str]:
    out: list[str] = []
    in_bullet = False
    for raw in lines:
        s = raw.strip()
        if _BULLET_RE.match(s):
            out.append("- " + _BULLET_RE.sub("", s))
            in_bullet = True
            continue
        if _is_subheading(raw):
            out += ["", f"#### {_HEADING_ICON_RE.sub('', s)}", ""]
            in_bullet = False
            continue
        prev = out[-1] if out else ""
        if re.search(r"[a-z] ?-$", prev) and s[:1].islower():
            out[-1] = re.sub(r" ?-$", "", prev) + s  # re-join hyphenated word
            continue
        s = _HEADING_ICON_RE.sub("", s)  # long icon lines: keep text
        if in_bullet:
            if not prev.rstrip().endswith(_SENT_END) or s[:1].islower():
                out[-1] = f"{prev} {s}"
                continue
            out.append("")  # bullet list ended
            in_bullet = False
        out.append(s)
        if s.endswith(_SENT_END) and len(s) < 40:
            out.append("")  # short last line of a paragraph
    return out


def pdf_to_markdown(pdf: Path, title: str, source_url: str = "") -> str:
    reader = pypdf.PdfReader(str(pdf))
    outline = _flatten_outline(reader)
    pages = _page_lines(reader, outline)
    n = len(pages)

    md = [f"# {title}", ""]
    if source_url:
        md += [f"<!-- source: {source_url} -->", ""]

    for i, (start, level, heading) in enumerate(outline):
        end = next((p for p, _, _ in outline[i + 1:] if p > start), n) - 1
        same_page_next = i + 1 < len(outline) and outline[i + 1][0] == start
        skip = heading.lower() in DEFAULT_SKIP
        pages_label = f"p. {start + 1}" if end <= start else f"p. {start + 1}-{end + 1}"
        if not skip:
            md += [f"{'#' * level} {heading} ({pages_label})", ""]
        if same_page_next or skip:
            continue  # body belongs to the next (more specific) heading
        for p in range(start, end + 1):
            md += _page_to_markdown(pages[p])
        md.append("")

    text = "\n".join(md)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--title", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--source-url", default="")
    args = ap.parse_args()
    md = pdf_to_markdown(args.pdf, args.title, args.source_url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"OK {args.pdf.name} -> {args.out} ({len(md.split())} words)")


if __name__ == "__main__":
    main()
