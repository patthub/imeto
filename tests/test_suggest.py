from pathlib import Path

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import ImpactLead, LeadSet
from imeto.phases.suggest import run_suggester, study_context, suggest_leads
from imeto.registries.skills import SkillRegistry


def test_study_context_uses_title_and_head():
    src = Source(
        local_identifier="d",
        title="Museums as spaces for debate",
        full_text="Authors: Krakowski, Manista. Study in 6 countries.",
    )
    ctx = study_context(src, max_chars=30)
    assert "Museums as spaces for debate" in ctx  # title
    assert "Authors: Krakowski" in ctx  # start of text (authors)


class FakeLeadLLM:
    model = "fake"

    def __init__(self, leads: LeadSet) -> None:
        self._l = leads

    def structured(self, system: str, user: str, schema: type[LeadSet]) -> LeadSet:
        return self._l


def _skills(tmp_path: Path) -> SkillRegistry:
    d = tmp_path / "knowledge" / "criteria" / "kryterium_iii"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("## Rubric\ntest", encoding="utf-8")
    return SkillRegistry(tmp_path / "knowledge")


def _two_claims(store: ProvenanceStore) -> list:
    text = "Method X was implemented. Model Y was developed."
    sid = store.add_source(Source(local_identifier="d", full_text=text))
    e1 = store.add_evidence(sid, "Method X was implemented")
    e2 = store.add_evidence(sid, "Model Y was developed")
    store.add_claim(sid, "Method X was implemented.", "direct", [e1])
    store.add_claim(sid, "Model Y was developed.", "direct", [e2])
    return store.claims_for_source(sid)


def test_suggest_maps_leads_to_claims(tmp_path: Path):
    store = ProvenanceStore()
    claims = _two_claims(store)
    leads = LeadSet(
        leads=[
            ImpactLead(
                based_on=1,
                lead="deployment in municipality",
                query="method X municipality",
            ),
            ImpactLead(based_on=2, lead="citation in report", query="model Y report"),
            ImpactLead(based_on=99, lead="out of scope", query="x"),  # bad number
        ]
    )
    got = suggest_leads(FakeLeadLLM(leads), _skills(tmp_path), claims)  # type: ignore[arg-type]

    assert [ld.claim_id for ld in got] == [c.id for c in claims]  # 99 skipped
    assert got[0].query == "method X municipality"


def test_suggest_empty_claims_no_call(tmp_path: Path):
    # no facts -> no model call (returns [] without touching llm)
    assert suggest_leads(None, _skills(tmp_path), [], "kryterium_iii") == []  # type: ignore[arg-type]


def test_run_suggester_persists_trail_and_lead(tmp_path: Path):
    # lead only for c1; c1→candidate+lead, c2→internal+no lead
    store = ProvenanceStore()
    claims = _two_claims(store)
    for c in claims:
        store.accept_claim(c.id)
    sid = claims[0].source_id
    c1, c2 = claims[0].id, claims[1].id
    leads = LeadSet(
        leads=[ImpactLead(based_on=1, lead="deployment", query="method X municipality")]
    )
    got = run_suggester(store, FakeLeadLLM(leads), _skills(tmp_path), sid)  # type: ignore[arg-type]

    assert len(got) == 1
    assert store.get_claim(c1).external_trail == "candidate"
    lead = store.get_lead(c1)
    assert lead is not None and lead.query == "method X municipality"  # saved, editable
    assert store.get_claim(c2).external_trail == "internal"  # marked, not hidden
    assert store.get_lead(c2) is None
