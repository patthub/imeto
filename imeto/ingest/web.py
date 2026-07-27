"""Fetching and extracting text from web pages (impact evidence from the web).

PDFs are parsed like a local file; HTML is cleaned with `trafilatura` down to the
main text (drops menus/boilerplate). Clean text is required for verbatim quote
anchoring — the same reason as `x_tolerance` for PDFs."""

import httpx

from imeto.ingest.parsing import parse_pdf_bytes

_UA = "IMeTo/0.1 (research; evidence anchoring)"  # ASCII: HTTP headers aren't UTF-8


def fetch_url_text(url: str, *, client: httpx.Client | None = None) -> str | None:
    """Fetches a page and returns its text (PDF or the main HTML text). None on
    failure — the caller decides what to do; never aborts."""
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
        # ponytail: pages are flaky (blocks, junk HTML) — failure -> None.
        return None
    finally:
        if own:
            c.close()
