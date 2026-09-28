"""Corroboration phase: for each fact in the document, search the web for
CONFIRMATION of its social impact and anchor it verbatim.

Fact-driven and automatic: fact → query → search → fetch candidates → LLM judges
whether the page confirms impact and supplies a VERBATIM quote → the quote is verified
character-for-character against that page (add_evidence) → external evidence linked to
the fact.

Anti-hallucination discipline: the confirmation MUST be a verbatim fragment of an
actually fetched page — the LLM cannot invent it. The search engine and pages return
CANDIDATES; the human judges which confirmations count (Z1)."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import Claim, ProvenanceStore, Source, SpanNotVerified
from imeto.core.schemas import Corroboration
from imeto.ingest.sources import source_from_text
from imeto.ingest.web import fetch_url_text
from imeto.phases.base import PhaseContext, PhaseResult
from imeto.phases.suggest import study_context
from imeto.tools.citations import citing_works, doi_of
from imeto.tools.web_search import SearchResult, web_search

CORROBORATE_SYSTEM = (
    "You check whether a PAGE confirms the SOCIAL IMPACT of the described FACT — a "
    "real effect outside science: deployment, adoption by an institution, citation in "
    "policy, change of practice. You are also given the STUDY CONTEXT "
    "(title/authors/topic). Return only JSON:\n"
    '{"confirms": true/false, "quote": "..."}\n'
    "- confirms: true ONLY when the page concerns THIS SPECIFIC study or its "
    "intervention (the same subject, authors, institution, method) AND confirms its "
    "impact. A page on a similar TOPIC but unrelated to this study = false.\n"
    "- quote: a VERBATIM fragment of the PAGE confirming the impact (copied character "
    "for character); empty when confirms=false.\n"
    "- Do not invent the quote. A shared keyword or the same general topic is NOT "
    "confirmation — a real connection to this study and its impact is required."
)


def corroborate_one(
    store: ProvenanceStore,
    llm: LLMClient,
    claim: Claim,
    *,
    query: str | None = None,
    context: str = "",
    citing: Sequence[SearchResult] = (),
    max_candidates: int = 3,
    page_chars: int = 6000,
    activity: str | None = None,
    agent: str | None = None,
) -> int | None:
    """Search for and anchor an impact confirmation for ONE fact. Returns the id of the
    (external) confirming evidence, or None. The quote must be verbatim on the page.

    `query` (from the suggester) targets the IMPACT lead; absent → search by fact text.
    `context` = the study's identity — the verdict rejects pages merely on a similar
    topic. `citing` = works citing this study (study-level, fetched once by the caller);
    they go FIRST, being documents that demonstrably used this work, not just its
    topic."""
    assert claim.id is not None
    cid = claim.id
    ctx = f"STUDY CONTEXT:\n{context}\n\n" if context else ""

    def first_confirmed(cands: Sequence[SearchResult], channel: str) -> int | None:
        # the channel is recorded in prov:wasGeneratedBy: "…:citation" (someone who
        # cited this work) is stronger evidence than "…:search" (a page found by words)
        act = f"{activity}:{channel}" if activity else None
        for cand in cands:
            text = fetch_url_text(cand.url)
            if not text:
                continue
            page = text[:page_chars]
            user = f"{ctx}FACT: {claim.statement}\n\nPAGE ({cand.url}):\n{page}"
            verdict = llm.structured(CORROBORATE_SYSTEM, user, Corroboration)
            if not verdict.confirms or not verdict.quote.strip():
                continue
            ext_sid, _ = source_from_text(store, cand.url, text)
            try:
                ev = store.add_evidence(
                    ext_sid, verdict.quote, activity=act, agent=agent
                )
            except SpanNotVerified:
                continue  # LLM invented the quote — reject, try the next candidate
            store.link_evidence(cid, ev)
            return ev
        return None

    # citations first; the search engine only if they yield nothing (saves a search
    # call per fact whenever a citing document already confirms the impact)
    ev_id = first_confirmed(citing, "citation")
    if ev_id is not None:
        return ev_id
    return first_confirmed(
        web_search(query or claim.statement, max_results=max_candidates), "search"
    )


def citations_for(
    src: Source, store: ProvenanceStore | None = None, max_results: int = 5
) -> list[SearchResult]:
    """Candidates that demonstrably used this work: first the documents the human
    PINNED (e.g. from impact leads), then OpenAlex's citing works (DOI only). One call
    per source — both the phase and the GUI go through here, so they cast the same
    net."""
    pinned = (
        [SearchResult(**c) for c in store.pinned_candidates(src.id)]
        if store is not None and src.id is not None
        else []
    )
    doi = doi_of(src)
    found = (
        citing_works(doi, max_results=max_results, contact_email=settings.contact_email)
        if doi
        else []
    )
    urls = {c.url for c in pinned}
    return pinned + [c for c in found if c.url not in urls]


@dataclass
class CorroboratePhase:
    source_id: int
    claim_status: str | None = "accepted"
    max_candidates: int = 3
    page_chars: int = 6000
    name: str = field(default="corroborate")

    def run(self, ctx: PhaseContext) -> PhaseResult:
        claims = ctx.store.claims_for_source(self.source_id, status=self.claim_status)
        if not claims:
            return PhaseResult(
                ok=False,
                summary=f"source {self.source_id}: no facts "
                f"(status={self.claim_status})",
            )
        src = ctx.store.get_source(self.source_id)
        # the study's identity — keeps search and verdict tied to THIS study
        context = study_context(src)
        # citation channel: one lookup per source, reused for every fact (impact is a
        # property of the study). No DOI (e.g. an uploaded file) → empty, search only.
        citing = citations_for(src, ctx.store)
        activity = f"corroborate:{self.source_id}"
        agent = ctx.llm.model
        produced: list[int] = []  # ids of confirming evidence
        for claim in claims:
            # Search EVERY fact. The lead from the store (suggester + optional human
            # edit) drives the query when present; no lead → search by fact text. The
            # 'internal' trail is only a hint, not a filter (we cast a wider net).
            lead = ctx.store.get_lead(claim.id) if claim.id is not None else None
            eid = corroborate_one(
                ctx.store,
                ctx.llm,
                claim,
                query=lead.query if lead is not None else None,
                context=context,
                citing=citing,
                max_candidates=self.max_candidates,
                page_chars=self.page_chars,
                activity=activity,
                agent=agent,
            )
            if eid is not None:
                produced.append(eid)
        summary = (
            f"source {self.source_id}: corroborated {len(produced)}/{len(claims)} "
            f"facts on the web"
        )
        return PhaseResult(
            ok=True, summary=summary, produced=produced, needs_human=True
        )
