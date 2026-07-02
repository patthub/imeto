"""Kotwice metadanych — pobieranie wytworów naukowych przez publiczne API.

- OpenAlex: główne źródło treści (tytuł, abstrakt, typ, status OA) po DOI.
- ORCID: punkt wejścia — lista prac danego badacza (zwraca DOI-e do rozwinięcia).

TWARDE OGRANICZENIE (ustalenie projektowe): z API mamy zwykle tylko ABSTRAKT, nie
pełny tekst. Fakty wolno wydobywać wyłącznie z tekstu, który faktycznie posiadamy —
więc `full_text` to na razie abstrakt. Dociąganie pełnego tekstu Open Access to
osobny, późniejszy krok. Formaty bez warstwy tekstowej są poza zakresem."""

from dataclasses import dataclass, field

import httpx

from imeto.worktypes import FABIO, WorkType

OPENALEX = "https://api.openalex.org"
ORCID = "https://pub.orcid.org/v3.0"

# typ OpenAlex -> nasz WorkType (podzbiór, który umiemy ekstrahować skillem)
_OPENALEX_TYPE: dict[str, WorkType] = {
    "article": WorkType.article,
    "report": WorkType.report,
}
_FABIO_FALLBACK = "http://purl.org/spar/fabio/Expression"


@dataclass
class FetchedWork:
    """Wytwór pobrany z API, gotowy do zapisu jako Source. `full_text` = abstrakt."""

    local_identifier: str
    title: str | None
    full_text: str
    fabio_type: str
    language: str | None
    identifiers: list[dict[str, str]] = field(default_factory=list)
    # najlepsze dopasowanie typu do skillu ekstrakcji; None = człowiek musi wskazać
    work_type: WorkType | None = None


def _abstract_from_index(index: dict[str, list[int]] | None) -> str:
    """Odtwarza abstrakt z odwróconego indeksu OpenAlex (słowo -> pozycje)."""
    if not index:
        return ""
    positioned = sorted(
        (pos, word) for word, positions in index.items() for pos in positions
    )
    return " ".join(word for _, word in positioned)


def _get(
    url: str,
    *,
    params: dict[str, str] | None,
    client: httpx.Client | None,
    headers: dict[str, str] | None = None,
) -> object:
    own = client is None
    c = client or httpx.Client(timeout=30.0)
    try:
        resp = c.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    finally:
        if own:
            c.close()


def fetch_by_doi(
    doi: str,
    *,
    contact_email: str | None = None,
    client: httpx.Client | None = None,
) -> FetchedWork:
    """Pobiera metadane i abstrakt wytworu z OpenAlex po DOI."""
    doi_clean = doi.strip().removeprefix("https://doi.org/")
    doi_clean = doi_clean.removeprefix("http://doi.org/")
    params = {"mailto": contact_email} if contact_email else None
    work = _get(f"{OPENALEX}/works/doi:{doi_clean}", params=params, client=client)
    assert isinstance(work, dict)

    wt = _OPENALEX_TYPE.get(str(work.get("type") or ""))
    fabio = FABIO[wt] if wt is not None else _FABIO_FALLBACK
    ids = work.get("ids") or {}
    identifiers = [{"scheme": k, "value": str(v)} for k, v in ids.items()]

    return FetchedWork(
        local_identifier=f"https://doi.org/{doi_clean}",
        title=work.get("title") or work.get("display_name"),
        full_text=_abstract_from_index(work.get("abstract_inverted_index")),
        fabio_type=fabio,
        language=work.get("language"),
        identifiers=identifiers,
        work_type=wt,
    )


def fetch_works_by_orcid(
    orcid: str, *, client: httpx.Client | None = None
) -> list[str]:
    """Zwraca listę DOI-ów prac powiązanych z danym ORCID (punkt wejścia)."""
    data = _get(
        f"{ORCID}/{orcid.strip()}/works",
        params=None,
        client=client,
        headers={"Accept": "application/json"},
    )
    assert isinstance(data, dict)
    dois: list[str] = []
    for group in data.get("group") or []:
        for summary in group.get("work-summary") or []:
            ext = (summary.get("external-ids") or {}).get("external-id") or []
            for eid in ext:
                if eid.get("external-id-type") == "doi":
                    dois.append(str(eid.get("external-id-value")))
    return dois
