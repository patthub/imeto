from imeto.core.chunking import chunk_text


def test_short_text_single_chunk():
    assert chunk_text("krótki tekst", max_chars=100) == ["krótki tekst"]


def test_long_text_splits_into_multiple():
    text = "\n".join(f"linia {i} z treścią" for i in range(60))
    chunks = chunk_text(text, max_chars=120, overlap=30)
    assert len(chunks) > 1


def test_no_content_lost():
    # każdy MARKER (w obrębie linii) trafia do jakiegoś fragmentu
    text = "\n".join(f"MARKER{i} wypełnienie linii tekstu" for i in range(40))
    chunks = chunk_text(text, max_chars=120, overlap=30)
    for i in range(40):
        assert any(f"MARKER{i} " in c for c in chunks), f"zgubiono MARKER{i}"


def test_overlap_clamped_does_not_hang():
    chunks = chunk_text("x" * 300, max_chars=100, overlap=999)
    assert len(chunks) >= 3  # overlap przycięty do połowy fragmentu
