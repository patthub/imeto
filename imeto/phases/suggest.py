"""Suggester: for accepted facts, propose LEADS — what to search the web for as
evidence of SOCIAL IMPACT and with what query.

This is the step before corroboration. A bare fact (a scientific claim) is a poor query
for finding impact — a lead translates "method X was developed" into "where X was
deployed / who adopted it / whether it was cited in policy" and yields a precise query.

A lead is a CANDIDATE (Z1), not a fact — it does not pass the gate and has no
provenance. It only becomes evidence via a verbatim quote from a found page (the
corroboration phase)."""

from dataclasses import dataclass

from imeto.core.llm import LLMClient
from imeto.core.provenance import Claim, ProvenanceStore, Source
from imeto.core.schemas import LeadSet
from imeto.registries.skills import SkillRegistry

SUGGEST_SYSTEM = (
    "You are given the STUDY CONTEXT (title, authors, topic) and numbered FACTS from "
    "it. For EVERY fact propose a LEAD + QUERY for finding external evidence of its "
    "social impact (deployment, adoption by an institution, citation in policy, change "
    "of practice, media echo), and flag whether the fact is internal. Return only "
    "JSON:\n"
    '{"leads": [{"based_on": 1, "internal": false, "lead": "...", "query": "..."}]}\n'
    "- based_on: the FACT number. Return one entry for EVERY fact.\n"
    "- internal: true when the fact likely has NO trace outside science (methodology, "
    "dates, sample size, authorship, publication metadata, a bare description of "
    "results). This is a HINT for the human, not a filter — still give it a query.\n"
    "- lead: what specifically to search for as evidence of impact, concisely.\n"
    "- query: the query MUST relate to THIS study — weave in distinguishing terms from "
    "the context (title, author surnames, the specific intervention/institution), not "
    "just the general topic; otherwise you will find random pages with similar words.\n"
    "- The rubric below says what counts as impact. Do not make things up — you only "
    "propose where to search; the evidence will be only a verbatim quote from a found "
    "page."
)


def study_context(src: Source, max_chars: int = 800) -> str:
    """Concise study identity (title + start of text: authors/abstract), so that
    search and verdict tie to THIS study, not to a general topic."""
    parts: list[str] = []
    if src.title:
        parts.append(f"Title: {src.title}")
    head = src.full_text[:max_chars].strip()
    if head:
        parts.append(head)
    return "\n".join(parts)


@dataclass
class Lead:
    claim_id: int
    statement: str
    lead: str
    query: str
    internal: bool = False  # model's hint; does NOT gate the search


def suggest_leads(
    llm: LLMClient,
    skills: SkillRegistry,
    claims: list[Claim],
    criterion: str = "kryterium_iii",
    context: str = "",
) -> list[Lead]:
    """One model call for all facts. Returns one lead per fact (query + `internal`
    hint), linked to facts by number (based_on). We search every fact; `internal` is
    only a hint shown to the human, not a filter. `context` = the study's identity."""
    if not claims:
        return []
    rubric = skills.load(criterion, subdir="criteria")
    system = f"{SUGGEST_SYSTEM}\n\n## Rubric\n{rubric}"
    ctx = f"## Study context\n{context}\n\n" if context else ""
    facts_text = "\n".join(f"[{i}] {c.statement}" for i, c in enumerate(claims, 1))
    result = llm.structured(system, f"{ctx}## Facts\n{facts_text}", LeadSet)

    by_index = {i: c for i, c in enumerate(claims, 1)}
    leads: list[Lead] = []
    for lead in result.leads:
        claim = by_index.get(lead.based_on)
        if claim is None or claim.id is None:
            continue
        leads.append(
            Lead(claim.id, claim.statement, lead.lead, lead.query, lead.internal)
        )
    return leads


def run_suggester(
    store: ProvenanceStore,
    llm: LLMClient,
    skills: SkillRegistry,
    source_id: int,
    criterion: str = "kryterium_iii",
    claim_status: str | None = "accepted",
) -> list[Lead]:
    """Runs the suggester and PERSISTS the result on the facts: stores a query per fact
    and sets `external_trail` from the model's `internal` hint (candidate/internal).
    The trail is only a hint — corroboration searches every fact regardless. Queries
    are editable and read from the store. Returns the leads (for preview)."""
    claims = store.claims_for_source(source_id, status=claim_status)
    if not claims:
        return []
    context = study_context(store.get_source(source_id))
    leads = suggest_leads(llm, skills, claims, criterion, context)
    by_claim = {ld.claim_id: ld for ld in leads}
    for c in claims:
        if c.id is None:
            continue
        ld = by_claim.get(c.id)
        if ld is not None:
            store.set_external_trail(c.id, "internal" if ld.internal else "candidate")
            store.upsert_lead(c.id, ld.lead, ld.query)
        else:  # model omitted this fact — no query; still searched by fact text
            store.set_external_trail(c.id, "internal")
            store.clear_lead(c.id)
    return leads
