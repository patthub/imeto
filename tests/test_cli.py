from pathlib import Path

import pytest
from docx import Document
from typer.testing import CliRunner

from imeto.cli import app
from imeto.config import settings
from imeto.core.schemas import ExtractedFact, Extraction

runner = CliRunner()


class FakeLLMClient:
    def __init__(self, **kwargs: object) -> None:
        self.model = str(kwargs.get("model", "fake"))

    def structured(
        self, system: str, user: str, schema: type[Extraction]
    ) -> Extraction:
        return Extraction(
            facts=[ExtractedFact(quote="przyjęła uchwałę nr 12", statement="Rada.")]
        )


def _make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("Rada gminy przyjęła uchwałę nr 12.")
    doc.save(str(path))
    return path


def test_run_extracts_and_prints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    doc = _make_docx(tmp_path / "s.docx")
    monkeypatch.setattr(settings, "db_url", "sqlite://")  # in-memory, bez pliku
    monkeypatch.setattr("imeto.cli.LLMClient", FakeLLMClient)

    result = runner.invoke(app, ["run", str(doc)])

    assert result.exit_code == 0
    assert "1 kandydatów zapisanych" in result.stdout
    assert "uchwałę nr 12" in result.stdout


def test_run_missing_file_errors():
    result = runner.invoke(app, ["run", "/nie/ma/takiego.docx"])
    assert result.exit_code != 0  # walidacja ścieżki przez Typer, bez dotykania modelu
