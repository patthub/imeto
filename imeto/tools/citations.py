"""Citation channel for impact corroboration: who CITES this work (OpenAlex).

A keyword search finds pages on the same topic; the citation graph finds documents
that actually used THIS work — exactly the question Criterion III asks. Returns
`SearchResult` candidates, same shape as `web_search`, so the corroboration phase
treats both channels alike: a candidate becomes evidence only through the verbatim
quote gate (Z1 — tools return candidates, not verdicts).

Study-level, not fact-level: one lookup per source, reused for all its facts.
"""

import httpx

from imeto.core.provenance import Source
from imeto.ingest.loaders import OPENALEX, _get
from imeto.tools.web_search import SearchResult

_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")


def doi_of(src: Source) -> str | None:
    """The source's DOI, if it has one — file uploads have none, and then this
    channel simply doesn't apply."""
    ident = src.local_identifier.strip()
    for prefix in _DOI_PREFIXES:
        if ident.lower().startswith(prefix):
            return ident[len(prefix) :]
    return ident if ident.startswith("10.") else None


def _best_url(work: dict[str, object]) -> str:
    """Where to fetch the citing work's text from: OA PDF first (parsable), then the
    landing page, then its DOI."""
    best = work.get("best_oa_location") or {}
    primary = work.get("primary_location") or {}
    assert isinstance(best, dict) and isinstance(primary, dict)
    for url in (
        best.get("pdf_url"),
        primary.get("pdf_url"),
        best.get("landing_page_url"),
        primary.get("landing_page_url"),
        work.get("doi"),
    ):
        if isinstance(url, str) and url:
            return url
    return ""


def citing_works(
    doi: str,
    *,
    max_results: int = 5,
    contact_email: str | None = None,
    client: httpx.Client | None = None,
) -> list[SearchResult]:
    """Works citing the given DOI, as corroboration candidates. Any API failure
    returns [] — the citation channel is a bonus, never a blocker for the search."""
    params = {"mailto": contact_email} if contact_email else {}

    def cited_by(flt: str) -> list[dict[str, object]]:
        page = {"filter": flt, "per-page": str(max_results)}
        data = _get(f"{OPENALEX}/works", params={**params, **page}, client=client)
        assert isinstance(data, dict)
        hits = data.get("results") or []
        assert isinstance(hits, list)
        return [w for w in hits if isinstance(w, dict)]

    try:
        work = _get(f"{OPENALEX}/works/doi:{doi}", params=params or None, client=client)
        assert isinstance(work, dict)
        work_id = str(work.get("id") or "").rsplit("/", 1)[-1]
        if not work_id:
            return []
        # OA first: a paywalled citing paper is a wasted candidate — we can't read a
        # verbatim quote out of a page we cannot fetch. Fall back to all citations
        # when none of them is open (their landing pages sometimes still parse).
        results = cited_by(f"cites:{work_id},open_access.is_oa:true") or cited_by(
            f"cites:{work_id}"
        )
    except Exception:  # noqa: BLE001 — no citations found is a normal outcome
        return []
    out: list[SearchResult] = []
    for w in results[:max_results]:
        url = _best_url(w)
        if not url:
            continue
        primary = w.get("primary_location")
        source = primary.get("source") if isinstance(primary, dict) else None
        venue = source.get("display_name") if isinstance(source, dict) else None
        parts = [str(p) for p in (venue, w.get("publication_year")) if p]
        out.append(
            SearchResult(
                title=str(w.get("title") or w.get("display_name") or ""),
                url=url,
                snippet=f"cites this work · {' · '.join(parts)}",
            )
        )
    return out
