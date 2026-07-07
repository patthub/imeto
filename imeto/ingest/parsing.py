"""Wczytywanie dokumentów PDF/DOCX do jednego kanonicznego `full_text`.

Offsety cytatów (Evidence.start/end) to indeksy znaków w tym stringu — to samo,
na czym operuje `core.span.find_span`. Dlatego parser zwraca po prostu tekst;
osobnej mapy pozycja→strona nie budujemy (§ POC: niepotrzebna warstwa)."""

import io
from pathlib import Path

import pdfplumber
from docx import Document


def parse_document(path: str | Path) -> str:
    """Zwraca pełny tekst dokumentu. Dispatch po rozszerzeniu."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".docx":
        return _parse_docx(p)
    if ext == ".pdf":
        return _parse_pdf(p)
    raise ValueError(f"nieobsługiwany format: {ext!r} (obsługiwane: .pdf, .docx)")


def _parse_docx(p: Path) -> str:
    doc = Document(str(p))
    # ponytail: same akapity — tabele/nagłówki dołożyć, gdy realny dokument ich wymaga.
    return "\n".join(para.text for para in doc.paragraphs)


def parse_pdf_bytes(data: bytes) -> str:
    """Parsuje PDF z bajtów (np. pobrany pełny tekst OA) — bez pliku tymczasowego."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _parse_pdf(p: Path) -> str:
    return parse_pdf_bytes(p.read_bytes())
