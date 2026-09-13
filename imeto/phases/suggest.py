"""Suggester: for accepted facts, propose LEADS — what to search the web for as
evidence of SOCIAL IMPACT and with what query.

This is the step before corroboration. A bare fact (a scientific claim) is a poor query
for finding impact — a lead translates "method X was developed" into "where X was
deployed / who adopted it / whether it was cited in policy" and yields a precise query.

A lead is a CANDIDATE (Z1), not a fact — it does not pass the gate and has no
provenance. It only becomes evidence via a verbatim quote from a found page (the
corroboration phase)."""

from collections.abc import Iterator
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
    '{"study_handle": "...", "leads": [{"based_on": 1, "internal": false, '
    '"lead": "...", "query": "..."}]}\n'
    "- study_handle: 2-6 words that identify THIS study and no other — its title or "
    "the author surnames, taken verbatim from the context. It is appended to every "
    "query, so do NOT repeat it inside the queries.\n"
    "- based_on: the FACT number. Return one entry for EVERY fact.\n"
    "- internal: true when the fact likely has NO trace outside science (methodology, "
    "dates, sample size, authorship, publication metadata, a bare description of "
    "results). This is a HINT for the human, not a filter — still give it a query.\n"
    "- lead: what specifically to search for as evidence of impact, concisely.\n"
    "- query: search-engine words for finding SOMEONE ELSE using this finding — who "
    "applied, implemented, cited or funded it. Lean on impact words (adopted, "
    "implemented, guidelines, programme, policy, curriculum, media) plus the subject "
    "of the fact; the study_handle is added by us, so you need not narrow it.\n"
    "- Keep query under 10 words and do NOT restate the fact's sentence — a search "
    "engine matches keywords, not prose.\n"
    "- ALWAYS fill in query, for EVERY fact, including ones you flagged internal. "
    'Never answer "N/A", "none" or an empty string — a weak query is fine, the '
    "human edits it before searching.\n"
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


# the model says "no lead" in words instead of leaving the field empty; searching the
# web for "N/A" is worse than not searching
_NO_QUERY = {"", "-", "n/a", "na", "none", "null"}


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
    """One model call for the given facts. Returns one lead per fact (query +
    `internal` hint), linked to facts by number (based_on). We search every fact;
    `internal` is only a hint shown to the human, not a filter. `context` = the study's
    identity. Callers pass ONE fact at a time (see `iter_suggester`) — a small local
    model times out generating a lead for a dozen facts in a single response."""
    if not claims:
        return []
    rubric = skills.load(criterion, subdir="criteria")
    system = f"{SUGGEST_SYSTEM}\n\n## Rubric\n{rubric}"
    ctx = f"## Study context\n{context}\n\n" if context else ""
    facts_text = "\n".join(f"[{i}] {c.statement}" for i, c in enumerate(claims, 1))
    result = llm.structured(system, f"{ctx}## Facts\n{facts_text}", LeadSet)

    # the handle is glued on HERE, not left to the model: a topic-only query finds
    # random pages on the same subject, which the corroboration verdict then rejects
    handle = result.study_handle.strip()
    by_index = {i: c for i, c in enumerate(claims, 1)}
    leads: list[Lead] = []
    for lead in result.leads:
        claim = by_index.get(lead.based_on)
        if claim is None or claim.id is None:
            continue
        query = lead.query.strip()
        # append the handle WHOLE or not at all — dropping its words one by one left
        # scrambled tails ("… Debate Education in Across"). If the query already
        # carries most of the handle's words, it identifies the study well enough.
        if handle and query.lower() not in _NO_QUERY:
            have = set(query.lower().split())
            words = handle.split()
            if sum(w.lower() in have for w in words) * 2 < len(words):
                query = f"{query} {handle}"
        leads.append(Lead(claim.id, claim.statement, lead.lead, query, lead.internal))
    return leads


def iter_suggester(
    store: ProvenanceStore,
    llm: LLMClient,
    skills: SkillRegistry,
    source_id: int,
    criterion: str = "kryterium_iii",
    claim_status: str | None = "accepted",
) -> Iterator[Lead]:
    """Suggests and PERSISTS one fact at a time, yielding each lead as it lands: stores
    a query per fact and sets `external_trail` from the model's `internal` hint
    (candidate/internal). The trail is only a hint — corroboration searches every fact
    regardless. Queries are editable and read from the store.

    One call per fact: a batched call for a dozen facts overruns the model timeout, and
    a failure mid-way would lose every earlier lead. A fact whose call fails is marked
    `internal` (no query) and the rest continue.
    ponytail: each call proposes its own study_handle — same context, so they come out
    near-identical; pin the first one only if they visibly drift."""
    claims = store.claims_for_source(source_id, status=claim_status)
    context = study_context(store.get_source(source_id)) if claims else ""
    for c in claims:
        if c.id is None:
            continue
        try:
            leads = suggest_leads(llm, skills, [c], criterion, context)
        except Exception:  # noqa: BLE001 — one dead fact must not kill the rest
            leads = []
        ld = leads[0] if leads else None
        if ld is not None and ld.query.strip().lower() not in _NO_QUERY:
            store.set_external_trail(c.id, "internal" if ld.internal else "candidate")
            store.upsert_lead(c.id, ld.lead, ld.query)
        else:  # no usable query — still searched by fact text if the human wants
            store.set_external_trail(c.id, "internal")
            store.clear_lead(c.id)
            ld = Lead(c.id, c.statement, "", "", internal=True)
        yield ld  # every fact, so a caller can show progress against the total


def run_suggester(
    store: ProvenanceStore,
    llm: LLMClient,
    skills: SkillRegistry,
    source_id: int,
    criterion: str = "kryterium_iii",
    claim_status: str | None = "accepted",
) -> list[Lead]:
    """`iter_suggester` to completion, keeping the facts that got a query (CLI and
    non-streaming callers)."""
    it = iter_suggester(store, llm, skills, source_id, criterion, claim_status)
    return [ld for ld in it if ld.query]
