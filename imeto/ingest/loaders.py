"""Metadata anchors — fetching scholarly works via public APIs.

- OpenAlex: primary content source (title, abstract, type, OA status) by DOI.
- ORCID: entry point — list of a researcher's works (returns DOIs to expand).

HARD LIMIT (design decision): the APIs usually give us only the ABSTRACT, not the
full text. Facts may be extracted only from text we actually hold — so for now
`full_text` is the abstract. Pulling Open Access full text is a separate, later
step. Formats without a text layer are out of scope."""

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from imeto.ingest.parsing import parse_pdf_bytes
from imeto.worktypes import FABIO, WorkType

OPENALEX = "https://api.openalex.org"
ORCID = "https://pub.orcid.org/v3.0"

# OpenAlex type -> our WorkType (subset we can extract with a skill)
_OPENALEX_TYPE: dict[str, WorkType] = {
    "article": WorkType.article,
    "report": WorkType.report,
}
_FABIO_FALLBACK = "http://purl.org/spar/fabio/Expression"


@dataclass
class FetchedWork:
    """Work fetched from an API, ready to store as a Source. `full_text` = abstract."""

    local_identifier: str
    title: str | None
    full_text: str
    fabio_type: str
    language: str | None
    identifiers: list[dict[str, str]] = field(default_factory=list)
    # best type match for the extraction skill; None = a human must pick
    work_type: WorkType | None = None
    is_oa: bool = False
    oa_pdf_url: str | None = None  # OA full text (PDF), if available
    signals: dict[str, object] = field(default_factory=dict)  # bibliometric context


def _abstract_from_index(index: dict[str, list[int]] | None) -> str:
    """Rebuilds the abstract from OpenAlex's inverted index (word -> positions)."""
    if not index:
        return ""
    positioned = sorted(
        (pos, word) for word, positions in index.items() for pos in positions
    )
    return " ".join(word for _, word in positioned)


class RateLimited(ValueError):
    """The API's budget is spent; retrying now won't help."""


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
        for attempt in range(3):
            resp = c.get(url, params=params, headers=headers)
            if resp.status_code != 429 or attempt == 2:
                break
            wait = float(resp.headers.get("Retry-After") or 1)
            # a burst throttle clears in a second; an exhausted DAILY budget says
            # "retry in 16 hours" — waiting that out would freeze the app
            if wait > 5:
                raise RateLimited(
                    f"OpenAlex daily limit reached — resets in {wait / 3600:.0f} h "
                    "(or set OPENALEX_API_KEY)"
                )
            time.sleep(wait)
        resp.raise_for_status()
        return resp.json()
    finally:
        if own:
            c.close()


def work_signals(work: dict[str, Any]) -> dict[str, Any]:
    """Context from a work record we already fetched (no extra call). Raw citation
    count and field only — normalized metrics mislead for SSH (see tools.signals)."""
    topic = work.get("primary_topic") or {}
    return {
        "openalex_id": str(work.get("id") or "").rsplit("/", 1)[-1] or None,
        "cited_by": work.get("cited_by_count"),
        "topic": topic.get("display_name"),
        "field": (topic.get("field") or {}).get("display_name"),
    }


def fetch_by_doi(
    doi: str,
    *,
    contact_email: str | None = None,
    client: httpx.Client | None = None,
) -> FetchedWork:
    """Fetches a work's metadata and abstract from OpenAlex by DOI."""
    doi_clean = doi.strip().removeprefix("https://doi.org/")
    doi_clean = doi_clean.removeprefix("http://doi.org/")
    params = {"mailto": contact_email} if contact_email else None
    work = _get(f"{OPENALEX}/works/doi:{doi_clean}", params=params, client=client)
    assert isinstance(work, dict)

    wt = _OPENALEX_TYPE.get(str(work.get("type") or ""))
    fabio = FABIO[wt] if wt is not None else _FABIO_FALLBACK
    ids = work.get("ids") or {}
    identifiers = [{"scheme": k, "value": str(v)} for k, v in ids.items()]
    oa = work.get("open_access") or {}
    best = work.get("best_oa_location") or {}
    pdf_url = best.get("pdf_url") or oa.get("oa_url")

    return FetchedWork(
        local_identifier=f"https://doi.org/{doi_clean}",
        title=work.get("title") or work.get("display_name"),
        full_text=_abstract_from_index(work.get("abstract_inverted_index")),
        fabio_type=fabio,
        language=work.get("language"),
        identifiers=identifiers,
        work_type=wt,
        is_oa=bool(oa.get("is_oa")),
        oa_pdf_url=pdf_url,
        signals=work_signals(work),
    )


def fetch_oa_fulltext(
    pdf_url: str, *, client: httpx.Client | None = None
) -> str | None:
    """Fetches and parses OA full text (PDF). Returns None on failure — then the
    caller falls back to the abstract. PDF only (HTML/landing out of scope)."""
    own = client is None
    c = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        resp = c.get(pdf_url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").lower()
        if "pdf" not in ctype and not pdf_url.lower().endswith(".pdf"):
            return None
        return parse_pdf_bytes(resp.content)
    except Exception:
        # ponytail: OA PDFs are flaky (redirects, corrupt files) —
        #           any failure -> None, fall back to the abstract, never crash.
        return None
    finally:
        if own:
            c.close()


def fetch_works_by_orcid(
    orcid: str, *, client: httpx.Client | None = None
) -> list[str]:
    """Returns the DOIs of works linked to a given ORCID (entry point)."""
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
