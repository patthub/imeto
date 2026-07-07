"""Pobieranie i wyciąganie tekstu ze stron WWW (dowody wpływu z sieci).

PDF parsujemy jak plik lokalny; HTML czyścimy `trafilatura` do głównego tekstu
(odrzuca menu/boilerplate). Czysty tekst jest konieczny do dosłownego kotwiczenia
cytatów — ten sam powód, co `x_tolerance` przy PDF."""

import httpx

from imeto.ingest.parsing import parse_pdf_bytes

_UA = "IMeTo/0.1 (research; evidence anchoring)"  # ASCII: nagłówki HTTP nie są UTF-8


def fetch_url_text(url: str, *, client: httpx.Client | None = None) -> str | None:
    """Pobiera stronę i zwraca jej tekst (PDF lub główny tekst HTML). None przy
    porażce — dzwoniący decyduje, co zrobić; nigdy nie przerywa."""
    own = client is None
    c = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        resp = c.get(url, headers={"User-Agent": _UA})
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            return parse_pdf_bytes(resp.content)
        import trafilatura  # lazy: extra 'search'

        text: str | None = trafilatura.extract(resp.text)
        return text
    except Exception:
        # ponytail: strony bywają zawodne (blokady, śmieciowy HTML) — porażka -> None.
        return None
    finally:
        if own:
            c.close()
