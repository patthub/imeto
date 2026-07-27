"""Split long text into chunks that fit the model's context window.

Chunks OVERLAP (a fact at a boundary is not lost) and cut on a paragraph or
sentence boundary, so a quote is never split mid-way. Quotes are verified later
against the whole `full_text` anyway, so offsets stay global."""


def chunk_text(text: str, max_chars: int = 6000, overlap: int = 400) -> list[str]:
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    overlap = min(overlap, max_chars // 2)  # sanity: overlap < half a chunk
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = start + max_chars
        if end >= n:
            chunks.append(text[start:])
            break
        # back the boundary up to a paragraph end, or a sentence end if none.
        # Paragraph split ("\n") is language-neutral and primary; the ". " sentence
        # fallback is Latin-centric best-effort. ponytail: don't add per-language
        # sentence rules (CJK 。, etc.) — a bad cut only costs a boundary fact to a
        # neighbouring chunk, never correctness (quotes are verified globally). If a
        # non-Latin script ever needs it, reach for unicode segmentation, not regex.
        boundary = text.rfind("\n", start, end)
        if boundary <= start:
            boundary = text.rfind(". ", start, end)
            boundary = boundary + 1 if boundary > start else end
        chunks.append(text[start:boundary])
        start = max(boundary - overlap, start + 1)  # overlap; always advances
    return chunks
