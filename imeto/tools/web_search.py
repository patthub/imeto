"""Wyszukiwanie dowodów wpływu (§10). Zwraca KANDYDATÓW, nie werdykty — człowiek
decyduje, co jest dowodem (Z1). Backend jest wymienny: domyślnie DuckDuckGo (bez
klucza, do POC), później API z kluczem lub konektor on-prem — wystarczy podmienić
funkcję `backend`."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

# backend: (query, max_results) -> iterowalne słowniki z kluczami title/href/body
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
    """Zwraca listę kandydatów (tytuł, url, snippet) dla zapytania."""
    return [
        SearchResult(
            title=r.get("title", ""),
            url=r.get("href", ""),
            snippet=r.get("body", ""),
        )
        for r in backend(query, max_results)
    ]
