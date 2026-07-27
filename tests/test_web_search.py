from collections.abc import Iterable

from imeto.tools.web_search import SearchResult, web_search


def _fake_backend(query: str, max_results: int) -> Iterable[dict[str, str]]:
    assert query and max_results > 0
    return [
        {
            "title": "MEN Report",
            "href": "https://gov.pl/raport",
            "body": "digitization",
        },
        {"title": "Media", "href": "https://news/x", "body": "research deployment"},
    ]


def test_web_search_maps_candidates():
    res = web_search("school digitization", backend=_fake_backend)
    assert len(res) == 2
    assert isinstance(res[0], SearchResult)
    assert res[0].url == "https://gov.pl/raport"
    assert res[1].title == "Media"


def test_web_search_handles_missing_fields():
    res = web_search("q", backend=lambda q, n: [{"title": "title only"}])
    assert res[0].url == "" and res[0].snippet == ""
