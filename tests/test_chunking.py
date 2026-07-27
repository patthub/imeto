from imeto.core.chunking import chunk_text


def test_short_text_single_chunk():
    assert chunk_text("short text", max_chars=100) == ["short text"]


def test_long_text_splits_into_multiple():
    text = "\n".join(f"line {i} with content" for i in range(60))
    chunks = chunk_text(text, max_chars=120, overlap=30)
    assert len(chunks) > 1


def test_no_content_lost():
    # every MARKER (within a line) ends up in some chunk
    text = "\n".join(f"MARKER{i} filler line of text" for i in range(40))
    chunks = chunk_text(text, max_chars=120, overlap=30)
    for i in range(40):
        assert any(f"MARKER{i} " in c for c in chunks), f"lost MARKER{i}"


def test_overlap_clamped_does_not_hang():
    chunks = chunk_text("x" * 300, max_chars=100, overlap=999)
    assert len(chunks) >= 3  # overlap clamped to half the chunk
