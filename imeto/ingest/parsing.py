"""Loading PDF/DOCX documents into a single canonical `full_text`.

Quote offsets (Evidence.start/end) are character indices into this string — the
same thing `core.span.find_span` operates on. So the parser just returns text;
we build no separate position→page map (§ POC: an unneeded layer)."""

import io
from pathlib import Path

import pdfplumber
from docx import Document


def parse_document(path: str | Path) -> str:
    """Returns the document's full text. Dispatches on the extension."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".docx":
        return _parse_docx(p)
    if ext == ".pdf":
        return _parse_pdf(p)
    raise ValueError(f"unsupported format: {ext!r} (supported: .pdf, .docx)")


def _parse_docx(p: Path) -> str:
    doc = Document(str(p))
    # ponytail: paragraphs only — add tables/headers when a real document needs them.
    return "\n".join(para.text for para in doc.paragraphs)


# x_tolerance=1 (instead of the default 3) separates words in tightly justified
# scholarly text — otherwise pdfplumber glues words together
# ("0.21phenotypicdimensions"), which breaks quote verification. ponytail: tuning
# knob; only if scholarly PDFs start needing column/table reads reach for SOTA
# (GROBID/docling), not before.
PDF_X_TOLERANCE = 1.0


def parse_pdf_bytes(data: bytes, x_tolerance: float = PDF_X_TOLERANCE) -> str:
    """Parses a PDF from bytes (e.g. fetched OA full text) — no temp file."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(
            page.extract_text(x_tolerance=x_tolerance) or "" for page in pdf.pages
        )


def _parse_pdf(p: Path) -> str:
    return parse_pdf_bytes(p.read_bytes())
