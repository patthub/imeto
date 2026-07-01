"""Weryfikacja kotwiczenia cytatu (poziom 3): dosłowne dopasowanie w źródle,
tolerancja wyłącznie na białe znaki. Rdzeń anty-halucynacji — czysta funkcja,
zero LLM, zero DB."""

import re

_WS = re.compile(r"\s+")


def find_span(full_text: str, quote: str) -> tuple[int, int] | None:
    """Zwraca (start, end) położenia cytatu w oryginalnym `full_text`, albo None.

    Znaki niebiałe muszą pasować dosłownie (wielkość liter, interpunkcja).
    Każdy ciąg białych znaków w cytacie dopasowuje dowolny ciąg białych znaków
    w źródle, więc offsety wskazują oryginał nawet gdy model zwinął spacje/newline.
    """
    words = _WS.split(quote.strip())
    if words == [""]:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pattern, full_text)
    # ponytail: pierwsze wystąpienie wystarcza — dowód potrzebuje jednej kotwicy,
    #           nie wszystkich. Rozszerzyć do finditer, gdy zajdzie potrzeba doboru.
    return m.span() if m else None
