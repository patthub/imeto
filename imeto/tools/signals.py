"""Impact LEADS from OpenAlex for an institution or a researcher — SSH only (domain 2:
Social Sciences incl. Arts & Humanities). The SSH-honest answer to commercial
"societal impact profiles".

Deliberately no normalized metrics (percentiles, FWCI, emerging topics, SDG labels):
for SSH they mislead — Polish-language journals and books are thinly covered, and
labels are a classifier's guesses. No "policy citations" either: OpenAlex barely
indexes policy documents, so a count would look authoritative and be wrong. What
stays is named and checkable:

- partners — non-academic organizations that CO-AUTHORED our works (potential impact),
- reports — our works typed as reports (grey literature, expert opinions),
- citing organizations — non-academic organizations whose people CITE our works
  (observed use beyond academia).

Every row is a candidate trail for Criterion III, never evidence (Z1): it becomes
evidence only through a source + verbatim quote, like anything else."""

import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import httpx

from imeto.ingest.loaders import OPENALEX, _get
from imeto.tools.citations import _best_url

SSH_DOMAIN = "2"  # ponytail: SSH only for now; a parameter when STEM users appear
NON_ACADEMIC = ("government", "nonprofit", "company", "healthcare", "archive", "other")
# OpenAlex types public research bodies (PAN, CNRS, Inserm, CSIC, CONICET) as
# "government" and university presses/schools as "other". Not "research" alone:
# that would drop think tanks like CASE. ponytail: name heuristic — misses odd
# names; the human hides the rest in the UI
_ACADEMIC_NAME = re.compile(
    r"academy of (sciences|learning)|akademi|universit|press\b|école|school|college"
    r"|recherche scientifique|institut national de (la )?recherche|recherche pour"
    r"|investigaciones científicas|consejo superior"
    r"|national research council|\b(cnrs|inserm|csic|conicet)\b|^department of",
    re.IGNORECASE,
)
_NOISE_TYPES = "type:!editorial,type:!paratext,type:!erratum,type:!retraction"
_OR_MAX = 100  # OpenAlex caps an OR-filter at 100 values
# ponytail: 5 parallel calls stay under OpenAlex's per-second throttle (429s are
#           retried in _get); raise with an API key if a profile gets slow
_WORKERS = 5

Params = dict[str, str]


def _pmap[T, R](fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
    with ThreadPoolExecutor(_WORKERS) as pool:
        return list(pool.map(fn, items))


def _chunks(xs: list[str], n: int = _OR_MAX) -> list[list[str]]:
    return [xs[i : i + n] for i in range(0, len(xs), n)]


def _short(url: object) -> str:
    return str(url).rsplit("/", 1)[-1]


def scope_filter(entity: str, years: str | None = None) -> str:
    """Works of an institution (I…) or a researcher (A…) in SSH. Pure."""
    y = years or default_years()
    key = (
        "authorships.author.id"
        if entity.startswith("A")
        else "authorships.institutions.id"
    )
    return f"{key}:{entity},primary_topic.domain.id:{SSH_DOMAIN},publication_year:{y}"


def default_years(today: date | None = None) -> str:
    """The evaluation-like window: five years back to now."""
    y = (today or date.today()).year
    return f"{y - 5}-{y}"


def is_non_academic(inst: dict[str, Any]) -> bool:
    """Pure — the partner filter, testable."""
    return inst.get("type") in NON_ACADEMIC and not _ACADEMIC_NAME.search(
        str(inst.get("display_name") or "")
    )


# --- raw OpenAlex access ---


def _works_page(
    params: Params, client: httpx.Client | None, **query: str
) -> dict[str, Any]:
    data = _get(f"{OPENALEX}/works", params={**params, **query}, client=client)
    assert isinstance(data, dict)
    return data


def _group_all(
    flt: str, by: str, params: Params, client: httpx.Client | None
) -> dict[str, int]:
    """{key: count} of a group_by, ALL groups (cursor-paged, not just the first 200)."""
    out: dict[str, int] = {}
    cursor = "*"
    while cursor:
        data = _works_page(
            params,
            client,
            filter=flt,
            group_by=by,
            **{"per-page": "200", "cursor": cursor},
        )
        for g in data.get("group_by") or []:
            out[_short(g["key"])] = int(g["count"])
        cursor = (data.get("meta") or {}).get("next_cursor") or ""
    return out


def _ids_all(flt: str, params: Params, client: httpx.Client | None) -> list[str]:
    """Ids of ALL works matching a filter (cursor-paged)."""
    out: list[str] = []
    cursor = "*"
    while cursor:
        data = _works_page(
            params,
            client,
            filter=flt,
            select="id",
            **{"per-page": "200", "cursor": cursor},
        )
        out += [_short(w["id"]) for w in data.get("results") or []]
        cursor = (data.get("meta") or {}).get("next_cursor") or ""
    return out


def _institutions(
    ids: list[str], params: Params, client: httpx.Client | None
) -> list[dict[str, Any]]:
    """Name, type and country for many institution ids (batched by 100)."""

    def one(batch: list[str]) -> list[dict[str, Any]]:
        data = _get(
            f"{OPENALEX}/institutions",
            params={
                **params,
                "filter": f"openalex:{'|'.join(batch)}",
                "per-page": str(_OR_MAX),
                "select": "id,display_name,type,country_code",
            },
            client=client,
        )
        assert isinstance(data, dict)
        return list(data.get("results") or [])

    return [i for rows in _pmap(one, _chunks(ids)) for i in rows]


def _org_rows(
    counts: dict[str, int], params: Params, client: httpx.Client | None
) -> list[dict[str, Any]]:
    """Counts per institution → named non-academic rows, most frequent first."""
    orgs = [
        i for i in _institutions(list(counts), params, client) if is_non_academic(i)
    ]
    rows = [
        {
            "id": _short(o["id"]),
            "name": o["display_name"],
            "type": o["type"],
            "country": o.get("country_code"),
            "works_count": counts[_short(o["id"])],
        }
        for o in orgs
    ]
    return sorted(rows, key=lambda r: r["works_count"], reverse=True)


def list_works(
    flt: str,
    *,
    limit: int = 50,
    params: Params | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Works for a lead list: newest first, editorials dropped, and one row per title
    (a preprint and its article are two OpenAlex works with one title)."""
    data = _works_page(
        params or {},
        client,
        filter=f"{flt},{_NOISE_TYPES}",
        select="id,title,doi,publication_year,type,primary_location",
        sort="publication_year:desc",
        **{"per-page": str(min(200, limit * 2))},
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for w in data.get("results") or []:
        title = w.get("title") or "(untitled)"
        if title.casefold() in seen:
            continue
        seen.add(title.casefold())
        venue = ((w.get("primary_location") or {}).get("source") or {}).get(
            "display_name"
        )
        out.append(
            {
                "id": _short(w["id"]),
                "title": title,
                "year": w.get("publication_year"),
                "doi": w.get("doi"),
                "type": w.get("type"),
                "venue": venue,
            }
        )
    return out[:limit]


# --- the three lead lists ---


def find_entities(
    query: str,
    kind: str = "institution",
    *,
    params: Params | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Candidates for a name — institutions or researchers; the human picks one."""
    if kind == "author":
        data = _get(
            f"{OPENALEX}/authors",
            params={
                **(params or {}),
                "search": query,
                "per-page": "8",
                "select": "id,display_name,last_known_institutions,works_count",
            },
            client=client,
        )
        assert isinstance(data, dict)
        return [
            {
                "id": _short(a["id"]),
                "display_name": a["display_name"],
                "detail": ", ".join(
                    i["display_name"] for i in a.get("last_known_institutions") or []
                ),
                "works_count": a.get("works_count", 0),
            }
            for a in data.get("results") or []
        ]
    data = _get(
        f"{OPENALEX}/institutions",
        params={
            **(params or {}),
            "search": query,
            "per-page": "8",
            "select": "id,display_name,country_code,works_count",
        },
        client=client,
    )
    assert isinstance(data, dict)
    return [
        {
            "id": _short(i["id"]),
            "display_name": i["display_name"],
            "detail": i.get("country_code") or "",
            "works_count": i.get("works_count", 0),
        }
        for i in data.get("results") or []
    ]


def partners(
    entity: str,
    *,
    years: str | None = None,
    params: Params | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """ALL non-academic organizations that co-authored the entity's SSH works."""
    p = params or {}
    types = f"authorships.institutions.type:{'|'.join(NON_ACADEMIC)}"
    flt = f"{scope_filter(entity, years)},{types}"
    counts = _group_all(flt, "authorships.institutions.id", p, client)
    counts.pop(entity, None)
    return _org_rows(counts, p, client)


def partner_works(
    entity: str,
    partner_id: str,
    *,
    years: str | None = None,
    params: Params | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """The entity's SSH works co-authored with one partner."""
    return list_works(
        f"{scope_filter(entity, years)},authorships.institutions.id:{partner_id}",
        limit=100,
        params=params,
        client=client,
    )


def reports(
    entity: str,
    *,
    years: str | None = None,
    params: Params | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """The entity's SSH works typed as reports (up to 200 — reports are rare)."""
    return list_works(
        f"{scope_filter(entity, years)},type:report",
        limit=200,
        params=params,
        client=client,
    )


def citing_orgs(
    entity: str,
    *,
    years: str | None = None,
    params: Params | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Non-academic organizations whose people cite the entity's SSH works — over ALL
    cited works, 100 per OR-filter. Returns the org rows plus `batches` (cited-work
    id groups) and `seen_in` (org → batch indexes), so a click on one org re-queries
    only the batches it appeared in."""
    p = params or {}
    cited = _ids_all(f"{scope_filter(entity, years)},cited_by_count:>0", p, client)
    batches = _chunks(cited)
    by = "authorships.institutions.id"
    types = f"authorships.institutions.type:{'|'.join(NON_ACADEMIC)}"
    groups = _pmap(
        lambda b: _group_all(f"cites:{'|'.join(b)},{types}", by, p, client), batches
    )
    counts: dict[str, int] = {}
    seen_in: dict[str, list[int]] = {}
    for i, g in enumerate(groups):
        for org, n in g.items():
            # ponytail: summed over batches — a work citing ours from two batches
            #           counts twice; exact per-org counts come with the click
            counts[org] = counts.get(org, 0) + n
            seen_in.setdefault(org, []).append(i)
    counts.pop(entity, None)
    return {
        "cited_works": len(cited),
        "orgs": _org_rows(counts, p, client),
        "batches": batches,
        "seen_in": seen_in,
    }


def org_citing_works(
    org_id: str,
    batches: list[list[str]],
    *,
    params: Params | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Works by one organization that cite any of the given cited-work batches."""
    rows = _pmap(
        lambda b: list_works(
            f"cites:{'|'.join(b)},authorships.institutions.id:{org_id}",
            limit=100,
            params=params,
            client=client,
        ),
        batches,
    )
    seen: set[str] = set()
    out = []
    for w in (w for ws in rows for w in ws):
        if w["id"] not in seen:
            seen.add(w["id"])
            out.append(w)
    return sorted(out, key=lambda w: w["year"] or 0, reverse=True)


# --- one work: reach, and the trail from a citing document back to our work ---


def work_reach(
    work_id: str, *, params: Params | None = None, client: httpx.Client | None = None
) -> dict[str, Any]:
    """Where a work's citations come from — countries and fields of the citing works.
    Plain counts, nothing normalized: feeds Criterion III's REACH dimension
    (international / national / regional) and shows use outside the home field."""
    p = params or {}
    by_country = _works_page(
        p,
        client,
        filter=f"cites:{work_id}",
        group_by="authorships.countries",
        **{"per-page": "200"},
    )
    by_field = _works_page(
        p,
        client,
        filter=f"cites:{work_id}",
        group_by="primary_topic.field.id",
        **{"per-page": "200"},
    )

    def rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "code": _short(g["key"]),
                "name": g["key_display_name"],
                "works": g["count"],
            }
            for g in data.get("group_by") or []
            if g.get("key") and g["key"] != "unknown"
        ]

    return {
        "citing": int((by_country.get("meta") or {}).get("count") or 0),
        "countries": rows(by_country),
        "fields": rows(by_field),
    }


def case_links(
    citing_id: str,
    cited: set[str],
    *,
    via: str = "",
    params: Params | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """For a citing document picked as a lead: the candidate itself (title/url/snippet,
    the shape corroboration consumes) and WHICH of our cited works it references."""
    p = params or {}
    data = _get(
        f"{OPENALEX}/works/{citing_id}",
        params={
            **p,
            "select": "id,title,doi,publication_year,best_oa_location,"
            "primary_location,referenced_works",
        },
        client=client,
    )
    assert isinstance(data, dict)
    ours = [w for w in map(_short, data.get("referenced_works") or []) if w in cited]
    found = (
        _works_page(
            p,
            client,
            filter=f"openalex:{'|'.join(ours[:_OR_MAX])}",
            select="id,doi,title",
            **{"per-page": str(_OR_MAX)},
        ).get("results")
        or []
        if ours
        else []
    )
    venue = ((data.get("primary_location") or {}).get("source") or {}).get(
        "display_name"
    )
    snippet = " · ".join(
        str(x)
        for x in (
            "pinned lead",
            via,
            "cites this work",
            venue,
            data.get("publication_year"),
        )
        if x
    )
    return {
        "candidate": {
            "title": str(data.get("title") or ""),
            "url": _best_url(data),
            "snippet": snippet,
        },
        "ours": [
            {"id": _short(w["id"]), "doi": w.get("doi"), "title": w.get("title")}
            for w in found
        ],
    }
