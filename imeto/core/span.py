"""Quote-anchoring verification (level 3): verbatim match against the source,
tolerant of whitespace only. The anti-hallucination core — a pure function,
zero LLM, zero DB."""

import re

_WS = re.compile(r"\s+")

# Folding typographic variants — LENGTH-PRESERVING (1 char -> 1 char), so offsets
# in the folded text line up with the original. Typographic quotes and dashes very
# often differ between the model and the source with no difference in content.
# ponytail: NFC/soft hyphen change length — deferred; when needed, normalize
#           full_text to NFC already at Source write time (offsets stay consistent).
_FOLD = str.maketrans(
    {
        "„": '"',
        "“": '"',
        "”": '"',
        "‟": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)


def _fold(text: str) -> str:
    return text.translate(_FOLD)


def find_span(full_text: str, quote: str) -> tuple[int, int] | None:
    """Return (start, end) of the quote in the original `full_text`, or None.

    Non-whitespace characters must match verbatim (case, punctuation), with one
    exception: typographic variants (curly quotes, dashes) are normalized. Any run
    of whitespace in the quote matches any run of whitespace in the source, so the
    offsets point at the original even when the model collapsed spaces/newlines or
    swapped „…" for "…".
    """
    words = _WS.split(quote.strip())
    if words == [""]:
        return None
    pattern = r"\s+".join(re.escape(_fold(w)) for w in words)
    m = re.search(pattern, _fold(full_text))
    # ponytail: the first match is enough — evidence needs one anchor, not all of
    #           them. Extend to finditer if picking among matches ever matters.
    return m.span() if m else None
