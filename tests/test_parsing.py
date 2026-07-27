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
        "The council adopted resolution no. 12.",
        "Regarding the budget for 2025.",
    )
    text = parse_document(p)
    assert "resolution no. 12" in text
    assert "the budget for 2025" in text


def test_parsed_text_is_anchorable(tmp_path: Path):
    # integration of step 6 with step 1: a quote from the loaded text can be anchored
    p = _make_docx(tmp_path / "t.docx", "The council adopted resolution no. 12.")
    text = parse_document(p)
    span = find_span(text, "adopted resolution no. 12")
    assert span is not None
    assert text[span[0] : span[1]] == "adopted resolution no. 12"


def test_unknown_extension_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        parse_document(tmp_path / "note.txt")
