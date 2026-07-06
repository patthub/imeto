"""Weryfikacja kotwiczenia cytatu (poziom 3): dosłowne dopasowanie w źródle,
tolerancja wyłącznie na białe znaki. Rdzeń anty-halucynacji — czysta funkcja,
zero LLM, zero DB."""

import re

_WS = re.compile(r"\s+")

# Folding wariantów typograficznych — ZACHOWUJE DŁUGOŚĆ (1 znak -> 1 znak), więc
# offsety w tekście złożonym pokrywają się z oryginałem. Cudzysłowy drukarskie i
# myślniki bardzo często różnią model od źródła bez różnicy w treści.
# ponytail: NFC/miękki łącznik zmieniają długość — odłożone; gdy zajdzie potrzeba,
#           normalizować full_text do NFC już przy zapisie Source (offsety spójne).
_FOLD = str.maketrans(
    {
        "„": '"', "“": '"', "”": '"', "‟": '"',
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "–": "-", "—": "-", "−": "-",
    }
)


def _fold(text: str) -> str:
    return text.translate(_FOLD)


def find_span(full_text: str, quote: str) -> tuple[int, int] | None:
    """Zwraca (start, end) położenia cytatu w oryginalnym `full_text`, albo None.

    Znaki niebiałe muszą pasować dosłownie (wielkość liter, interpunkcja), z jednym
    wyjątkiem: warianty typograficzne (cudzysłowy drukarskie, myślniki) są ujednolicane.
    Każdy ciąg białych znaków w cytacie dopasowuje dowolny ciąg białych znaków w źródle,
    więc offsety wskazują oryginał nawet gdy model zwinął spacje/newline lub zamienił
    „…" na "…".
    """
    words = _WS.split(quote.strip())
    if words == [""]:
        return None
    pattern = r"\s+".join(re.escape(_fold(w)) for w in words)
    m = re.search(pattern, _fold(full_text))
    # ponytail: pierwsze wystąpienie wystarcza — dowód potrzebuje jednej kotwicy,
    #           nie wszystkich. Rozszerzyć do finditer, gdy zajdzie potrzeba doboru.
    return m.span() if m else None
