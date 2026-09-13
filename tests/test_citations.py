import httpx
import respx

from imeto.core.provenance import Source
from imeto.tools.citations import citing_works, doi_of


def test_doi_of_reads_the_identifier_or_gives_up():
    assert doi_of(Source(local_identifier="https://doi.org/10.1/x", full_text="")) == (
        "10.1/x"
    )
    assert doi_of(Source(local_identifier="10.1/x", full_text="")) == "10.1/x"
    # an uploaded file has no DOI → the citation channel simply doesn't apply
    assert doi_of(Source(local_identifier="/tmp/report.pdf", full_text="")) is None


@respx.mock
def test_citing_works_returns_candidates_with_fetchable_urls():
    respx.get("https://api.openalex.org/works/doi:10.1/x").mock(
        return_value=httpx.Response(200, json={"id": "https://openalex.org/W7"})
    )
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {  # OA pdf wins — parsable text
                        "title": "Policy report",
                        "publication_year": 2025,
                        "best_oa_location": {"pdf_url": "https://gov.pl/r.pdf"},
                        "primary_location": {
                            "landing_page_url": "https://gov.pl/r",
                            "source": {"display_name": "Ministry"},
                        },
                    },
                    {  # no location at all → falls back to the DOI
                        "title": "Follow-up study",
                        "doi": "https://doi.org/10.2/y",
                    },
                    {"title": "Unreachable"},  # nothing to fetch → dropped
                ]
            },
        )
    )

    cands = citing_works("10.1/x", contact_email="a@b.pl")

    assert [c.url for c in cands] == ["https://gov.pl/r.pdf", "https://doi.org/10.2/y"]
    assert cands[0].title == "Policy report"
    assert "cites this work" in cands[0].snippet and "Ministry" in cands[0].snippet


@respx.mock
def test_citing_works_swallows_api_failure():
    # the citation channel is a bonus — a dead API must not block the search channel
    respx.get("https://api.openalex.org/works/doi:10.1/x").mock(
        return_value=httpx.Response(500)
    )
    assert citing_works("10.1/x") == []
