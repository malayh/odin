from odin.services.chunking import _ntokens, chunk


def test_small_doc_is_single_chunk():
    text = "Hello world."
    chunks = chunk(text)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.ordinal == 0
    assert (c.char_start, c.char_end) == (0, len(text))
    assert c.text == text


def test_char_ranges_reconstruct_source():
    text = ("para one. " * 200) + "\n\n" + ("para two words here. " * 200)
    chunks = chunk(text, max_tokens=100, overlap_tokens=20)
    assert len(chunks) > 1
    for i, c in enumerate(chunks):
        assert c.ordinal == i
        assert text[c.char_start : c.char_end] == c.text
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)


def test_consecutive_chunks_overlap():
    text = " ".join(f"word{i}" for i in range(2000))
    chunks = chunk(text, max_tokens=100, overlap_tokens=30)
    assert len(chunks) > 1
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start < a.char_end


def test_chunking_is_deterministic():
    text = "alpha beta gamma " * 400
    assert chunk(text, max_tokens=80, overlap_tokens=16) == chunk(
        text, max_tokens=80, overlap_tokens=16
    )


def test_heading_path_captured():
    text = "# Top\n\nintro\n\n## Sub\n\ndetail here\n"
    chunks = chunk(text, max_tokens=10, overlap_tokens=2)
    paths = [c.section_meta["headings"] for c in chunks]
    assert any("Top" in p for p in paths)


def test_no_headings_yields_empty_path():
    chunks = chunk("just some plain prose without structure")
    assert chunks[0].section_meta["headings"] == []


def test_trailing_sliver_merges_into_previous():
    text = "word " * 530
    two = chunk(text, max_tokens=512, overlap_tokens=8, min_tokens=1)
    assert len(two) == 2
    assert _ntokens(two[-1].text) < 64
    merged = chunk(text, max_tokens=512, overlap_tokens=8, min_tokens=64)
    assert len(merged) == 1
    assert merged[-1].char_end == len(text)
    assert text[merged[-1].char_start : merged[-1].char_end] == merged[-1].text
