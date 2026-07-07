"""Dzielenie długiego tekstu na fragmenty mieszczące się w kontekście modelu.

Fragmenty NAKŁADAJĄ się (fakt przy granicy nie ginie) i tną się na granicy akapitu
lub zdania, by nie rozcinać cytatu w środku. Cytaty i tak weryfikujemy potem względem
całego `full_text`, więc offsety pozostają globalne."""


def chunk_text(text: str, max_chars: int = 6000, overlap: int = 400) -> list[str]:
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    overlap = min(overlap, max_chars // 2)  # sanity: nakładka < pół fragmentu
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = start + max_chars
        if end >= n:
            chunks.append(text[start:])
            break
        # cofnij granicę do końca akapitu, a jeśli brak — do końca zdania
        boundary = text.rfind("\n", start, end)
        if boundary <= start:
            boundary = text.rfind(". ", start, end)
            boundary = boundary + 1 if boundary > start else end
        chunks.append(text[start:boundary])
        start = max(boundary - overlap, start + 1)  # nakładka; zawsze do przodu
    return chunks
