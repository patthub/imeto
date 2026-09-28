"""GUI logic, framework-free: JSON-ready views of the store and the long operations
as generators of progress events. The HTTP skin is `server.py`, the front is `web/`.

Everything here is testable without a browser and without a live model."""

import csv
import functools
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date
from typing import Any

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import Argument, Claim, Evidence, ProvenanceStore, Source
from imeto.core.schemas import SPHERES
from imeto.ingest.loaders import fetch_by_doi, fetch_oa_fulltext
from imeto.ingest.sources import (
    FABIO_WEBPAGE,
    source_from_fetched,
    source_from_file,
    source_from_url,
)
from imeto.phases.argumenter import ArgumenterPhase
from imeto.phases.base import PhaseContext
from imeto.phases.corroborate import citations_for, corroborate_one
from imeto.phases.extract import ExtractPhase
from imeto.phases.suggest import iter_suggester, study_context
from imeto.registries.skills import SkillRegistry
from imeto.tools import signals
from imeto.tools.citations import doi_of
from imeto.worktypes import FABIO, WorkType

Candidates = list[tuple[int, str]]
# progress of a long operation: {"status": …} replaces the previous status line,
# {"log": …} is a line worth keeping (a confirmation, a citing work)
Event = dict[str, str]

# CSV export: all visible with provenance and context, nothing vanishes silently
FACTS_HEADERS = [
    "No.",
    "Kind",
    "Fact",
    "Quote in source",
    "Position",
    "Context",
    "Lead / query",
    "Impact (web)",
]

_TRAIL_MARK = {
    "candidate": "🔍",
    "internal": "internal (hint)",
    "unknown": "—",
}

_WORK_TYPE = {uri: wt for wt, uri in FABIO.items()}


def _around(text: str, start: int, end: int, pad: int = 120) -> tuple[str, str]:
    """Text before and after a quote — the fact seen in its sentence, not alone."""
    a, b = max(0, start - pad), min(len(text), end + pad)
    before = ("…" if a > 0 else "") + " ".join(text[a:start].split())
    after = " ".join(text[end:b].split()) + ("…" if b < len(text) else "")
    return before, after


def _context_window(text: str, start: int, end: int, pad: int = 120) -> str:
    before, after = _around(text, start, end, pad)
    return " ".join(p for p in (before, " ".join(text[start:end].split()), after) if p)


def _channel(ev: Evidence) -> str:
    """citation = a work that CITES this study (it demonstrably used it);
    search = a page a keyword search turned up. Matters when judging."""
    act = ev.generated_by_activity or ""
    return "citation" if act.endswith(":citation") else "search"


def _impact_cell(store: ProvenanceStore, ev: Evidence) -> str:
    ident = store.get_source(ev.source_id).local_identifier
    mark = "📚 cited by" if _channel(ev) == "citation" else "🔍 web"
    return f"{mark}: „{ev.quote}” — {ident}"


def facts_rows(store: ProvenanceStore, claim_ids: list[int]) -> list[list[str]]:
    """Claims table rows (CSV): kind, statement, verbatim grounds + position,
    surroundings, and external impact corroboration (empty = „—")."""
    rows: list[list[str]] = []
    for n, cid in enumerate(claim_ids, 1):
        claim = store.get_claim(cid)
        src = store.get_source(claim.source_id)
        evs = store.evidence_for_claim(cid)
        own = [e for e in evs if e.source_id == claim.source_id]
        ext = [e for e in evs if e.source_id != claim.source_id]
        cytat = " | ".join(f"„{e.quote}”" for e in own)
        pozycja = " | ".join(f"{e.start}–{e.end}" for e in own)
        kontekst = (
            _context_window(src.full_text, own[0].start, own[0].end) if own else ""
        )
        lead = store.get_lead(cid)
        slad = (
            f"🔍 {lead.query}"
            if lead is not None
            else _TRAIL_MARK.get(claim.external_trail, "—")
        )
        wplyw = " | ".join(_impact_cell(store, e) for e in ext) or "—"
        rows.append(
            [str(n), claim.kind, claim.statement, cytat, pozycja, kontekst, slad, wplyw]
        )
    return rows


def facts_csv(store: ProvenanceStore, claim_ids: list[int]) -> str:
    """Writes the claims table to CSV (a wide table is handier in a spreadsheet than in
    the browser). utf-8-sig BOM → Excel reads Polish characters correctly."""
    path = tempfile.NamedTemporaryFile(
        delete=False, suffix=".csv", prefix="facts_"
    ).name
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(FACTS_HEADERS)
        w.writerows(facts_rows(store, claim_ids))
    return path


# --- views (what the front renders) ---


def is_study(src: Source) -> bool:
    """A source the operator brought in — not a web page fetched as impact evidence.
    ponytail: tells them apart by FaBiO type; a `role` column if a study is ever a
    WebPage."""
    return src.fabio_type != FABIO_WEBPAGE


def source_title(src: Source) -> str:
    if src.title:
        return src.title
    ident = src.local_identifier
    return ident if ident.startswith("http") else ident.rsplit("/", 1)[-1]


def visible_claims(store: ProvenanceStore, source_id: int) -> list[Claim]:
    """The source's facts, minus those superseded by a later extraction run (rejected
    by `extract:…`, not by a human — a human's rejection stays visible to undo)."""
    return [
        c
        for c in store.claims_for_source(source_id)
        if not (c.status == "rejected" and (c.approved_by or "").startswith("extract:"))
    ]


def fact_view(store: ProvenanceStore, src: Source, claim: Claim) -> dict[str, Any]:
    assert claim.id is not None
    evs = store.evidence_for_claim(claim.id)
    grounds = []
    for e in evs:
        if e.source_id == claim.source_id:
            before, after = _around(src.full_text, e.start, e.end)
            grounds.append(
                {"quote": e.quote, "start": e.start, "end": e.end}
                | {"before": before, "after": after}
            )
    impact = [
        {
            "quote": e.quote,
            "url": store.get_source(e.source_id).local_identifier,
            "channel": _channel(e),
        }
        for e in evs
        if e.source_id != claim.source_id
    ]
    lead = store.get_lead(claim.id)
    return {
        "id": claim.id,
        "kind": claim.kind,
        "statement": claim.statement,
        "status": claim.status,
        "trail": claim.external_trail,
        "query": lead.query if lead is not None else "",
        "grounds": grounds,
        "impact": impact,
    }


def argument_view(store: ProvenanceStore, arg: Argument) -> dict[str, Any]:
    assert arg.id is not None
    return {
        "id": arg.id,
        "side": arg.side,
        "statement": arg.statement,
        "status": arg.status,
        "sphere": arg.sphere,
        "facts": [c.statement for c in store.claims_for_argument(arg.id)],
    }


def sources_list(store: ProvenanceStore) -> list[dict[str, Any]]:
    """Sidebar and dashboard rows: each study with the counts that say where it stands.
    ponytail: a few queries per fact — fine for one operator's library; one aggregate
    query in the store if the dashboard gets slow."""
    out: list[dict[str, Any]] = []
    for s in store.list_sources():
        if s.id is None or not is_study(s):
            continue
        claims = visible_claims(store, s.id)
        ids = [c.id for c in claims if c.id is not None]
        doi = doi_of(s)
        out.append(
            {
                "id": s.id,
                "title": source_title(s),
                "sub": f"doi:{doi}" if doi else s.local_identifier.rsplit("/", 1)[-1],
                "facts": len(claims),
                "candidate": sum(c.status == "candidate" for c in claims),
                "accepted": sum(c.status == "accepted" for c in claims),
                "queries": sum(store.get_lead(i) is not None for i in ids),
                "impact": sum(bool(store.external_evidence_for_claim(i)) for i in ids),
                "arguments": len(store.arguments_for_source(s.id)),
            }
        )
    return out


def source_view(store: ProvenanceStore, source_id: int) -> dict[str, Any]:
    s = store.get_source(source_id)
    text = s.full_text or ""
    return {
        "id": source_id,
        "title": source_title(s),
        "identifier": s.local_identifier,
        "type": s.fabio_type.rsplit("/", 1)[-1] if s.fabio_type else None,
        "language": s.language,
        "doi": doi_of(s),
        "chars": len(text),
        "head": " ".join(text[:600].split()),
        "signals": store.get_signals(source_id),
        "facts": [fact_view(store, s, c) for c in visible_claims(store, source_id)],
        "arguments": [
            argument_view(store, a) for a in store.arguments_for_source(source_id)
        ],
    }


def with_reach(sig: dict[str, Any]) -> dict[str, Any]:
    """Adds where the work's citations come from. Best effort: a failed lookup must
    not block the import — the source just shows no reach."""
    wid = sig.get("openalex_id")
    if not wid:
        return sig
    try:
        return {
            **sig,
            "reach": signals.work_reach(wid, params=settings.openalex_params),
        }
    except Exception:  # noqa: BLE001 — reach is context, never a blocker
        return sig


def refresh_signals(store: ProvenanceStore, source_id: int) -> dict[str, Any] | None:
    """Re-fetches a DOI source's OpenAlex context (it goes stale). A source without a
    DOI has none — returns None, not an error. Pinned candidates are kept."""
    doi = doi_of(store.get_source(source_id))
    if doi is None:
        return None
    sig = with_reach(fetch_by_doi(doi, contact_email=settings.contact_email).signals)
    store.set_signals(source_id, sig)
    return store.get_signals(source_id)


# --- impact leads (OpenAlex, SSH): candidates to follow, never evidence ---

# an OpenAlex institution (I…) or author (A…) id — it lands inside a filter string,
# so anything else (commas, colons) is rejected rather than escaped
_ENTITY = re.compile(r"^[IA]\d{1,12}$")


def check_entity(entity: str) -> str:
    if not _ENTITY.match(entity):
        raise ValueError(f"not an OpenAlex institution/author id: {entity!r}")
    return entity


# ponytail: in-process caches per (entity, day) — leads move slowly, a full scan of
#           a big university costs ~100+ OpenAlex calls; a DB cache if restarts hurt
@functools.cache
def _partners(entity: str, day: date) -> list[dict[str, Any]]:
    return signals.partners(entity, params=settings.openalex_params)


@functools.cache
def _reports(entity: str, day: date) -> list[dict[str, Any]]:
    return signals.reports(entity, params=settings.openalex_params)


@functools.cache
def _citing(entity: str, day: date) -> dict[str, Any]:
    return signals.citing_orgs(entity, params=settings.openalex_params)


def leads_partners(entity: str) -> list[dict[str, Any]]:
    return _partners(check_entity(entity), date.today())


def leads_partner_works(entity: str, partner: str) -> list[dict[str, Any]]:
    return signals.partner_works(
        check_entity(entity), check_entity(partner), params=settings.openalex_params
    )


def leads_reports(entity: str) -> list[dict[str, Any]]:
    return _reports(check_entity(entity), date.today())


def leads_citing(entity: str) -> dict[str, Any]:
    """Citing organizations without the internal batch bookkeeping."""
    c = _citing(check_entity(entity), date.today())
    return {"cited_works": c["cited_works"], "orgs": c["orgs"]}


def build_case(store: ProvenanceStore, entity: str, citing: str, via: str = "") -> int:
    """From a lead to a case: the citing document the human picked is pinned as the
    first corroboration candidate on OUR work(s) it cites, each imported as a source.
    The phases stay human-gated — this only sets the case up. Returns the first
    source's id."""
    c = _citing(check_entity(entity), date.today())
    cited = {w for batch in c["batches"] for w in batch}
    if not re.match(r"^W\d{1,12}$", citing):
        raise ValueError(f"not an OpenAlex work id: {citing!r}")
    links = signals.case_links(citing, cited, via=via, params=settings.openalex_params)
    if not links["candidate"]["url"]:
        raise ValueError("The citing document has no reachable URL.")
    sids: list[int] = []
    # ponytail: first 3 of our works it cites — a review citing 20 of ours is 20
    #           cases; the human opens the rest from the list
    for ours in [w for w in links["ours"] if w["doi"]][:3]:
        sid = load_source(store, "DOI", None, ours["doi"], "", WorkType.article, True)
        store.pin_candidate(sid, links["candidate"])
        sids.append(sid)
    if not sids:
        raise ValueError("None of our works it cites has a DOI to import.")
    return sids[0]


def leads_citing_works(entity: str, org: str) -> list[dict[str, Any]]:
    c = _citing(check_entity(entity), date.today())
    batches = [c["batches"][i] for i in c["seen_in"].get(check_entity(org), [])]
    return signals.org_citing_works(org, batches, params=settings.openalex_params)


# --- edits (the human gate) ---


def save_query(store: ProvenanceStore, claim_id: int, query: str) -> bool:
    """Writes a query the human edited. The query is a CANDIDATE (Z1) — the human owns
    it. Emptied → the lead is cleared and corroboration falls back to the fact's own
    text. Returns whether a query is now stored."""
    q = query.strip()
    if not q:
        store.clear_lead(claim_id)
        return False
    lead = store.get_lead(claim_id)
    store.upsert_lead(claim_id, lead.lead if lead is not None else "", q)
    return True


def set_accepted(store: ProvenanceStore, claim_id: int, accepted: bool) -> None:
    """The human gate on a fact."""
    if accepted:
        store.accept_claim(claim_id, by="operator")
    else:
        store.reject_claim(claim_id, by="operator")


def set_argument_sphere(store: ProvenanceStore, arg_id: int, sphere: str) -> None:
    """The human's correction; "" clears it."""
    if sphere and sphere not in SPHERES:
        raise ValueError(f"unknown sphere {sphere!r}")
    store.set_argument_sphere(arg_id, sphere or None)


def set_argument_accepted(store: ProvenanceStore, arg_id: int, accepted: bool) -> None:
    if accepted:
        store.accept_argument(arg_id, by="expert")
    else:
        store.reject_argument(arg_id, by="expert")


# --- sources and phases ---


def _run_phase(
    store: ProvenanceStore,
    skills: SkillRegistry,
    source_id: int,
    work_type: WorkType,
    llm: LLMClient,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Candidates:
    ctx = PhaseContext(store=store, llm=llm, skills=skills)
    phase = ExtractPhase(
        source_id,
        work_type,
        chunk_chars=settings.chunk_chars,
        on_progress=on_progress,
        should_stop=should_stop,
    )
    result = phase.run(ctx)
    out: Candidates = []
    for cid in result.produced:
        claim = store.get_claim(cid)
        grounds = " | ".join(f"„{ev.quote}”" for ev in store.evidence_for_claim(cid))
        out.append((cid, f"({claim.kind}) {claim.statement} — {grounds}"))
    return out


def extract_candidates(
    store: ProvenanceStore,
    skills: SkillRegistry,
    document: str,
    work_type: WorkType,
    llm: LLMClient,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, Candidates]:
    source_id, _ = source_from_file(store, document, work_type)
    return source_id, _run_phase(
        store, skills, source_id, work_type, llm, on_progress, should_stop
    )


def extract_candidates_from_doi(
    store: ProvenanceStore,
    skills: SkillRegistry,
    doi: str,
    work_type: WorkType,
    llm: LLMClient,
    full_text: bool = False,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, Candidates]:
    fetched = fetch_by_doi(doi, contact_email=settings.contact_email)
    if full_text and fetched.oa_pdf_url:
        text = fetch_oa_fulltext(fetched.oa_pdf_url)
        if text:
            fetched = replace(fetched, full_text=text)
    source_id, _ = source_from_fetched(store, fetched)
    return source_id, _run_phase(
        store, skills, source_id, work_type, llm, on_progress, should_stop
    )


def extract_candidates_from_url(
    store: ProvenanceStore,
    skills: SkillRegistry,
    url: str,
    work_type: WorkType,
    llm: LLMClient,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, Candidates]:
    source_id, _ = source_from_url(store, url, work_type)
    return source_id, _run_phase(
        store, skills, source_id, work_type, llm, on_progress, should_stop
    )


def load_source(
    store: ProvenanceStore,
    mode: str,
    document: str | None,
    doi: str,
    url: str,
    work_type: WorkType,
    full_text: bool = False,
) -> int:
    """Fetch/create the Source WITHOUT extracting, so the human reviews it first.
    Raises ValueError on missing input."""
    if mode == "DOI":
        if not doi.strip():
            raise ValueError("Provide a DOI.")
        fetched = fetch_by_doi(doi.strip(), contact_email=settings.contact_email)
        fetched = replace(fetched, signals=with_reach(fetched.signals))
        if full_text and fetched.oa_pdf_url:
            text = fetch_oa_fulltext(fetched.oa_pdf_url)
            if text:
                fetched = replace(fetched, full_text=text)
        sid, _ = source_from_fetched(store, fetched)
    elif mode == "URL":
        if not url.strip():
            raise ValueError("Provide a URL.")
        sid, _ = source_from_url(store, url.strip(), work_type)
    else:
        if not document:
            raise ValueError("Upload a document.")
        sid, _ = source_from_file(store, document, work_type)
    return sid


def argue_candidates(
    store: ProvenanceStore,
    skills: SkillRegistry,
    source_id: int,
    llm: LLMClient,
    criterion: str = "kryterium_iii",
) -> Candidates:
    """Builds FOR/AGAINST/GAPS arguments over the source's ACCEPTED claims."""
    ctx = PhaseContext(store=store, llm=llm, skills=skills)
    result = ArgumenterPhase(source_id, criterion).run(ctx)
    out: Candidates = []
    for aid in result.produced:
        arg = store.get_argument(aid)
        facts = " | ".join(c.statement for c in store.claims_for_argument(aid))
        tail = f"  ← {facts}" if facts else ""
        out.append((aid, f"[{arg.side.upper()}] {arg.statement}{tail}"))
    return out


# --- long operations as event streams ---


def extract_events(
    store: ProvenanceStore,
    skills: SkillRegistry,
    source_id: int,
    llm: LLMClient,
    stop: threading.Event,
) -> Iterator[Event]:
    """Extraction in a thread, a status tick every second (a local model takes minutes).
    Stop is cooperative: the current chunk finishes, then the phase halts."""
    src = store.get_source(source_id)
    wt = _WORK_TYPE.get(src.fabio_type, WorkType.report)
    prog = {"msg": ""}
    box: dict[str, Any] = {}

    def note(m: str) -> None:
        prog["msg"] = m

    def run() -> None:
        try:
            box["ok"] = _run_phase(store, skills, source_id, wt, llm, note, stop.is_set)
        except Exception as e:  # noqa: BLE001 — re-raised in the caller's thread
            box["err"] = e

    th = threading.Thread(target=run)
    th.start()
    t0 = time.time()
    while th.is_alive():
        el = int(time.time() - t0)
        if stop.is_set():
            yield {"status": f"Stopping after the current chunk · {el}s"}
        else:
            detail = f" · {prog['msg']}" if prog["msg"] else ""
            yield {"status": f"Extracting facts · {el}s{detail}"}
        th.join(timeout=1.0)
    if "err" in box:
        raise box["err"]
    yield {"log": f"Extracted {len(box['ok'])} facts — tick the ones you keep."}


def suggest_events(
    store: ProvenanceStore,
    skills: SkillRegistry,
    source_id: int,
    llm: LLMClient,
    stop: threading.Event,
) -> Iterator[Event]:
    """Proposes a query per accepted fact and STOPS — the human edits the queries
    before searching."""
    n = len(store.claims_for_source(source_id, status="accepted"))
    if not n:
        yield {"log": "No approved facts — tick facts first."}
        return
    for i, _ in enumerate(iter_suggester(store, llm, skills, source_id), 1):
        yield {"status": f"Proposing search queries · {i}/{n}"}
        if stop.is_set():
            break
    yield {"log": "Queries proposed — edit them, then corroborate."}


def corroborate_events(
    store: ProvenanceStore,
    skills: SkillRegistry,
    source_id: int,
    llm: LLMClient,
    stop: threading.Event,
) -> Iterator[Event]:
    targets = [
        c
        for c in store.claims_for_source(source_id, status="accepted")
        if c.id is not None
    ]
    if not targets:
        yield {"log": "No approved facts — tick facts first."}
        return
    src = store.get_source(source_id)
    context = study_context(src)
    yield {"status": "Asking OpenAlex who cites this work"}
    citing = citations_for(src, store)  # once per source, reused for every fact
    if citing:
        yield {"log": f"{len(citing)} citing works — checked before the search engine"}
        for c in citing:
            yield {"log": f"cited by: {c.title[:90]} — {c.url}"}
    else:
        why = "no DOI" if doi_of(src) is None else "none found"
        yield {"log": f"Citation channel: {why} — searching the web only."}
    # no stored queries → the human skipped the propose step; propose them here so a
    # single click still works end to end
    if not any(store.get_lead(c.id) for c in targets if c.id is not None):
        yield from suggest_events(store, skills, source_id, llm, stop)
    found = 0
    for i, claim in enumerate(targets, 1):
        assert claim.id is not None
        if stop.is_set():
            yield {"log": f"Stopped at {i - 1}/{len(targets)}."}
            return
        lead = store.get_lead(claim.id)
        yield {"status": f"Checking {i}/{len(targets)} · {claim.statement[:70]}"}
        try:
            eid = corroborate_one(
                store,
                llm,
                claim,
                query=lead.query if lead is not None else None,
                context=context,
                citing=citing,
                activity=f"corroborate:{source_id}",
                agent=llm.model,
            )
        except Exception as e:  # noqa: BLE001 — one failing fact must not end the run
            yield {"log": f"Error on fact {i}: {e}"}
            continue
        if eid is not None:
            found += 1
            yield {"log": f"Confirmed: {claim.statement[:90]}"}
    yield {"log": f"Corroboration done — {found}/{len(targets)} facts confirmed."}
