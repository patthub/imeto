import sys
import types

import httpx
import pytest
import respx

from imeto.ingest.web import fetch_url_text


@respx.mock
def test_fetch_html_uses_trafilatura(monkeypatch: pytest.MonkeyPatch):
    fake = types.ModuleType("trafilatura")
    fake.extract = lambda html: "GŁÓWNY TEKST STRONY"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "trafilatura", fake)
    respx.get("https://x/page").mock(
        return_value=httpx.Response(
            200, text="<html>...</html>", headers={"content-type": "text/html"}
        )
    )
    assert fetch_url_text("https://x/page") == "GŁÓWNY TEKST STRONY"


@respx.mock
def test_fetch_pdf_uses_parser(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("imeto.ingest.web.parse_pdf_bytes", lambda b: "TEKST PDF")
    respx.get("https://x/doc.pdf").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    assert fetch_url_text("https://x/doc.pdf") == "TEKST PDF"


@respx.mock
def test_fetch_error_returns_none():
    respx.get("https://x/missing").mock(return_value=httpx.Response(404))
    assert fetch_url_text("https://x/missing") is None
