from rag.chunking import (
    DEFAULT_MAX_WORDS,
    chunk_document,
    fixed_chunks,
    logical_lines,
    sentence_chunks,
    split_sentences,
)

MANUAL = """# Pump Manual

## 4. Startup Procedure (p. 12-13)

Before starting, complete the following steps:

1. Open suction valve fully.
2. Vent the casing until water flows without air.
3. Start the motor and watch the ammeter.
4. Open the discharge valve slowly over 30 seconds.

## 5. Limits (p. 14)

| Parameter | Alarm | Trip |
|---|---|---|
| Bearing temperature | 80 C | 90 C |
| Vibration | 4.5 mm/s | 7.1 mm/s |
"""


def test_logical_lines_rejoins_wrapped_prose():
    text = "Centrifugal pumps are widely\nused because of their\nlow maintenance.\n\n- item one\n- item two"
    assert logical_lines(text) == [
        "Centrifugal pumps are widely used because of their low maintenance.",
        "- item one",
        "- item two",
    ]


def test_split_sentences_keeps_list_items_whole():
    units = split_sentences("First sentence. Second one.\n1. Do this. Then that.\n2. Next step.")
    assert units == ["First sentence.", "Second one.", "1. Do this. Then that.", "2. Next step."]


def test_fixed_chunks_overlap():
    text = " ".join(str(i) for i in range(250))
    chunks = [t for _, t in fixed_chunks(text, size=100, overlap=20)]
    assert len(chunks) == 3
    assert chunks[1].split()[0] == "80"  # 100 - 20


def test_sentence_windows_overlap_by_one():
    text = "A one. B two. C three. D four. E five."
    windows = [t for _, t in sentence_chunks(text, window=2, overlap=1)]
    assert windows[0] == "A one. B two."
    assert windows[1] == "B two. C three."


def test_section_chunks_keep_procedure_together_with_intro():
    chunks = chunk_document(MANUAL, "manual.md", "section")
    startup = [c for c in chunks if "Startup" in c.section]
    assert len(startup) == 1
    text = startup[0].text
    assert "complete the following steps:" in text and "4. Open the discharge valve" in text


def test_section_chunks_breadcrumb_short_in_text_full_in_metadata():
    chunks = chunk_document(MANUAL, "manual.md", "section")
    limits = next(c for c in chunks if "Limits" in c.section)
    assert limits.text.startswith("[Pump Manual > 5. Limits]")  # 2 levels, no page numbers
    assert limits.section == "Pump Manual > 5. Limits (p. 14)"  # citation keeps pages
    assert "| Bearing temperature | 80 C | 90 C |" in limits.text


def test_long_procedure_is_split_between_steps_with_overlap():
    steps = "\n".join(f"{i}. " + "word " * 20 + "end." for i in range(1, 21))
    doc = f"# M\n\n## Proc\n\nDo this:\n\n{steps}\n"
    chunks = chunk_document(doc, "m.md", "section", max_words=100)
    assert len(chunks) > 1
    for c in chunks:
        assert c.words <= 100
        body = c.text.split("\n", 1)[1]
        assert body.startswith("Do this:")  # intro repeated in every piece
    # one-step overlap: the last step of chunk n is the first step of chunk n+1
    last_step = chunks[0].text.splitlines()[-1]
    assert chunks[1].text.splitlines()[2] == last_step


def test_no_chunk_exceeds_budget_on_long_prose():
    doc = "# T\n\n## S\n\n" + " ".join(f"Sentence number {i} is here." for i in range(200))
    for c in chunk_document(doc, "t.md", "section"):
        assert c.words <= DEFAULT_MAX_WORDS


def test_plain_text_without_headings_uses_file_title():
    chunks = chunk_document("Fact one.\nFact two.", "about_me.txt", "section")
    assert chunks[0].section == "about me"
