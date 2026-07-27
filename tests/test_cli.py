from pathlib import Path

import httpx
import pytest
import respx
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
            facts=[
                ExtractedFact(
                    statement="The council adopted.",
                    kind="direct",
                    quotes=["adopted resolution no. 12"],
                )
            ]
        )


def _make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("The council adopted resolution no. 12.")
    doc.save(str(path))
    return path


def test_run_extracts_and_prints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    doc = _make_docx(tmp_path / "s.docx")
    monkeypatch.setattr(settings, "db_url", "sqlite://")  # in-memory, no file
    monkeypatch.setattr("imeto.cli.LLMClient", FakeLLMClient)

    result = runner.invoke(app, ["run", str(doc), "--type", "report"])

    assert result.exit_code == 0
    assert "1 facts saved" in result.stdout
    assert "(direct)" in result.stdout
    assert "resolution no. 12" in result.stdout


def test_run_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    doc = _make_docx(tmp_path / "s.docx")
    monkeypatch.setattr(
        settings, "db_url", f"sqlite:///{tmp_path}/t.db"
    )  # persistent db
    monkeypatch.setattr("imeto.cli.LLMClient", FakeLLMClient)

    r1 = runner.invoke(app, ["run", str(doc), "--type", "report"])
    r2 = runner.invoke(app, ["run", str(doc), "--type", "report"])

    assert r1.exit_code == 0 and r2.exit_code == 0
    assert "1 facts saved" in r1.stdout
    assert "already imported" in r2.stdout  # no crash, no duplicate


def test_run_missing_file_errors():
    result = runner.invoke(app, ["run", "/nie/ma/takiego.docx"])
    assert result.exit_code != 0  # path validation by Typer, without touching the model


@respx.mock
def test_ingest_doi_fetches_and_extracts(monkeypatch: pytest.MonkeyPatch):
    respx.get("https://api.openalex.org/works/doi:10.1/x").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "Work",
                "type": "article",
                "abstract_inverted_index": {
                    "The": [0],
                    "council": [1],
                    "adopted": [2],
                    "resolution": [3],
                    "no.": [4],
                    "12": [5],
                },
            },
        )
    )
    monkeypatch.setattr(settings, "db_url", "sqlite://")
    monkeypatch.setattr("imeto.cli.LLMClient", FakeLLMClient)

    result = runner.invoke(app, ["ingest", "--doi", "10.1/x", "--type", "article"])

    assert result.exit_code == 0
    assert "1 facts saved" in result.stdout
    assert "resolution no. 12" in result.stdout


@respx.mock
def test_ingest_orcid_lists_dois():
    respx.get("https://pub.orcid.org/v3.0/0000-0002-1825-0097/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "group": [
                    {
                        "work-summary": [
                            {
                                "external-ids": {
                                    "external-id": [
                                        {
                                            "external-id-type": "doi",
                                            "external-id-value": "10.1/a",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            },
        )
    )
    result = runner.invoke(app, ["ingest", "--orcid", "0000-0002-1825-0097"])
    assert result.exit_code == 0
    assert "10.1/a" in result.stdout
