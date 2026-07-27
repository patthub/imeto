import httpx
import pytest
import respx

from imeto.ingest.loaders import (
    FetchedWork,
    _abstract_from_index,
    fetch_by_doi,
    fetch_oa_fulltext,
    fetch_works_by_orcid,
)
from imeto.worktypes import WorkType


def test_abstract_reconstruction_from_inverted_index():
    idx = {"Model": [0], "achieved": [1], "92%": [2]}
    assert _abstract_from_index(idx) == "Model achieved 92%"
    assert _abstract_from_index(None) == ""
    assert _abstract_from_index({}) == ""


@respx.mock
def test_fetch_by_doi_maps_fields():
    respx.get("https://api.openalex.org/works/doi:10.1234/x").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "Impact of digital education",
                "type": "article",
                "language": "en",
                "ids": {"doi": "https://doi.org/10.1234/x", "openalex": "W1"},
                "abstract_inverted_index": {"Trained": [0], "128": [1]},
            },
        )
    )
    work = fetch_by_doi("10.1234/x")
    assert isinstance(work, FetchedWork)
    assert work.title == "Impact of digital education"
    assert work.work_type == WorkType.article
    assert work.fabio_type.endswith("JournalArticle")
    assert work.full_text == "Trained 128"
    assert work.local_identifier == "https://doi.org/10.1234/x"
    assert {"scheme": "doi", "value": "https://doi.org/10.1234/x"} in work.identifiers


@respx.mock
def test_fetch_by_doi_unknown_type_has_no_worktype():
    respx.get("https://api.openalex.org/works/doi:10.1/book").mock(
        return_value=httpx.Response(200, json={"title": "Book", "type": "book"})
    )
    work = fetch_by_doi("https://doi.org/10.1/book")
    assert work.work_type is None  # human must specify the type
    assert work.fabio_type.endswith("Expression")  # fallback


@respx.mock
def test_fetch_by_doi_extracts_oa_pdf_url():
    respx.get("https://api.openalex.org/works/doi:10.1/oa").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "OA Work",
                "type": "article",
                "open_access": {"is_oa": True, "oa_url": "https://x/paper.pdf"},
                "best_oa_location": {"pdf_url": "https://x/best.pdf"},
            },
        )
    )
    w = fetch_by_doi("10.1/oa")
    assert w.is_oa is True
    assert w.oa_pdf_url == "https://x/best.pdf"  # best_oa_location takes precedence


@respx.mock
def test_fetch_oa_fulltext_parses_pdf(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("imeto.ingest.loaders.parse_pdf_bytes", lambda b: "FULL TEXT")
    respx.get("https://x/best.pdf").mock(
        return_value=httpx.Response(
            200, content=b"%PDF-fake", headers={"content-type": "application/pdf"}
        )
    )
    assert fetch_oa_fulltext("https://x/best.pdf") == "FULL TEXT"


@respx.mock
def test_fetch_oa_fulltext_non_pdf_returns_none():
    respx.get("https://x/landing").mock(
        return_value=httpx.Response(
            200, content=b"<html>", headers={"content-type": "text/html"}
        )
    )
    assert fetch_oa_fulltext("https://x/landing") is None


@respx.mock
def test_fetch_oa_fulltext_http_error_returns_none():
    respx.get("https://x/missing.pdf").mock(return_value=httpx.Response(404))
    assert fetch_oa_fulltext("https://x/missing.pdf") is None


@respx.mock
def test_fetch_works_by_orcid_extracts_dois():
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
                                        },
                                        {
                                            "external-id-type": "eid",
                                            "external-id-value": "ignore",
                                        },
                                    ]
                                }
                            }
                        ]
                    },
                    {"work-summary": [{"external-ids": {"external-id": []}}]},
                ]
            },
        )
    )
    assert fetch_works_by_orcid("0000-0002-1825-0097") == ["10.1/a"]
