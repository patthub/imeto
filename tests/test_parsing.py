from pathlib import Path

import pytest
from docx import Document

from imeto.core.span import find_span
from imeto.ingest.parsing import parse_document


def _make_docx(path: Path, *paragraphs: str) -> Path:
    doc = Document()
    for para in paragraphs:
        doc.add_paragraph(para)
    doc.save(str(path))
    return path


def test_parse_docx_returns_text(tmp_path: Path):
    p = _make_docx(
        tmp_path / "t.docx",
        "Rada gminy przyjęła uchwałę nr 12.",
        "W sprawie budżetu na rok 2025.",
    )
    text = parse_document(p)
    assert "uchwałę nr 12" in text
    assert "budżetu na rok 2025" in text


def test_parsed_text_is_anchorable(tmp_path: Path):
    # integracja kroku 6 z krokiem 1: cytat z wczytanego tekstu daje się zakotwiczyć
    p = _make_docx(tmp_path / "t.docx", "Rada gminy przyjęła uchwałę nr 12.")
    text = parse_document(p)
    span = find_span(text, "przyjęła uchwałę nr 12")
    assert span is not None
    assert text[span[0] : span[1]] == "przyjęła uchwałę nr 12"


def test_unknown_extension_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        parse_document(tmp_path / "notatka.txt")
