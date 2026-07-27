"""Searching for impact evidence (§10). Returns CANDIDATES, not verdicts — a human
decides what is evidence (Z1). The backend is swappable: DuckDuckGo by default (no
key, for the POC), later a keyed API or an on-prem connector — just swap the
`backend` function."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

# backend: (query, max_results) -> iterable of dicts with keys title/href/body
Backend = Callable[[str, int], Iterable[dict[str, str]]]


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def _ddg(query: str, max_results: int) -> Iterable[dict[str, str]]:
    from ddgs import DDGS  # lazy: extra 'search'

    results: Iterable[dict[str, str]] = DDGS().text(query, max_results=max_results)
    return results


def web_search(
    query: str, max_results: int = 8, backend: Backend = _ddg
) -> list[SearchResult]:
    """Returns a list of candidates (title, url, snippet) for the query."""
    return [
        SearchResult(
            title=r.get("title", ""),
            url=r.get("href", ""),
            snippet=r.get("body", ""),
        )
        for r in backend(query, max_results)
    ]
