import httpx
import respx

from imeto.ingest.loaders import (
    FetchedWork,
    _abstract_from_index,
    fetch_by_doi,
    fetch_works_by_orcid,
)
from imeto.worktypes import WorkType


def test_abstract_reconstruction_from_inverted_index():
    idx = {"Model": [0], "osiągnął": [1], "92%": [2]}
    assert _abstract_from_index(idx) == "Model osiągnął 92%"
    assert _abstract_from_index(None) == ""
    assert _abstract_from_index({}) == ""


@respx.mock
def test_fetch_by_doi_maps_fields():
    respx.get("https://api.openalex.org/works/doi:10.1234/x").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "Wpływ edukacji cyfrowej",
                "type": "article",
                "language": "pl",
                "ids": {"doi": "https://doi.org/10.1234/x", "openalex": "W1"},
                "abstract_inverted_index": {"Przeszkolono": [0], "128": [1]},
            },
        )
    )
    work = fetch_by_doi("10.1234/x")
    assert isinstance(work, FetchedWork)
    assert work.title == "Wpływ edukacji cyfrowej"
    assert work.work_type == WorkType.article
    assert work.fabio_type.endswith("JournalArticle")
    assert work.full_text == "Przeszkolono 128"
    assert work.local_identifier == "https://doi.org/10.1234/x"
    assert {"scheme": "doi", "value": "https://doi.org/10.1234/x"} in work.identifiers


@respx.mock
def test_fetch_by_doi_unknown_type_has_no_worktype():
    respx.get("https://api.openalex.org/works/doi:10.1/book").mock(
        return_value=httpx.Response(200, json={"title": "Książka", "type": "book"})
    )
    work = fetch_by_doi("https://doi.org/10.1/book")
    assert work.work_type is None  # człowiek musi wskazać typ
    assert work.fabio_type.endswith("Expression")  # fallback


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
