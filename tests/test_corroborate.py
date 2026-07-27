import pytest

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import Corroboration
from imeto.phases import corroborate as C
from imeto.phases.base import PhaseContext
from imeto.phases.corroborate import CorroboratePhase
from imeto.registries.skills import SkillRegistry
from imeto.tools.web_search import SearchResult


class FakeLLM:
    model = "fake"

    def __init__(self, verdict: Corroboration) -> None:
        self._v = verdict

    def structured(self, system: str, user: str, schema: type) -> Corroboration:
        return self._v


def _one_accepted_fact(store: ProvenanceStore) -> tuple[int, int]:
    src = Source(local_identifier="doc", full_text="The pilot program was published.")
    sid = store.add_source(src)
    e = store.add_evidence(sid, "The pilot program was published")
    c = store.add_claim(sid, "The pilot program was published.", "direct", [e])
    store.accept_claim(c)
    return sid, c


def _mock_search_fetch(monkeypatch: pytest.MonkeyPatch, page_text: str) -> None:
    hit = [SearchResult("t", "https://gov.pl/x", "s")]
    monkeypatch.setattr(C, "web_search", lambda q, max_results=3: hit)
    monkeypatch.setattr(C, "fetch_url_text", lambda url: page_text)


def test_corroborate_anchors_external_confirmation(monkeypatch: pytest.MonkeyPatch):
    store = ProvenanceStore()
    sid, c = _one_accepted_fact(store)
    _mock_search_fetch(monkeypatch, "The pilot was officially deployed in 2025.")
    verdict = Corroboration(confirms=True, quote="The pilot was officially deployed")
    ctx = PhaseContext(store=store, llm=FakeLLM(verdict), skills=SkillRegistry("."))  # type: ignore[arg-type]

    result = CorroboratePhase(sid).run(ctx)

    assert len(result.produced) == 1
    ev = store.get_evidence(result.produced[0])
    # the evidence comes from the EXTERNAL page and is linked to the fact
    assert store.get_source(ev.source_id).local_identifier == "https://gov.pl/x"
    linked = store.evidence_for_claim(c)
    assert any(x.source_id != sid for x in linked)  # external confirmation linked


def test_corroborate_rejects_non_verbatim_quote(monkeypatch: pytest.MonkeyPatch):
    store = ProvenanceStore()
    sid, c = _one_accepted_fact(store)
    _mock_search_fetch(monkeypatch, "A page about something entirely different.")
    verdict = Corroboration(confirms=True, quote="a fabricated quote that isn't there")
    ctx = PhaseContext(store=store, llm=FakeLLM(verdict), skills=SkillRegistry("."))  # type: ignore[arg-type]

    result = CorroboratePhase(sid).run(ctx)
    assert result.produced == []  # quote does not appear verbatim -> rejected


def test_corroborate_confirms_false_skips(monkeypatch: pytest.MonkeyPatch):
    store = ProvenanceStore()
    sid, _ = _one_accepted_fact(store)
    _mock_search_fetch(monkeypatch, "The pilot was officially deployed.")
    verdict = Corroboration(confirms=False, quote="")
    ctx = PhaseContext(store=store, llm=FakeLLM(verdict), skills=SkillRegistry("."))  # type: ignore[arg-type]
    assert CorroboratePhase(sid).run(ctx).produced == []


def test_corroborate_searches_internal_facts_too(monkeypatch: pytest.MonkeyPatch):
    # 'internal' is only a hint now — we cast a wider net and search c2 as well
    store = ProvenanceStore()
    src = Source(local_identifier="doc", full_text="X was deployed. Study from 2021.")
    sid = store.add_source(src)
    e1 = store.add_evidence(sid, "X was deployed")
    e2 = store.add_evidence(sid, "Study from 2021")
    c1 = store.add_claim(sid, "X was deployed.", "direct", [e1])
    c2 = store.add_claim(sid, "Study from 2021.", "direct", [e2])
    store.accept_claim(c1)
    store.accept_claim(c2)
    store.set_external_trail(c1, "candidate")
    store.upsert_lead(c1, "deployment", "X deployment municipality")
    store.set_external_trail(c2, "internal")  # internal — but still searched
    _mock_search_fetch(monkeypatch, "X was deployed in the municipality.")
    verdict = Corroboration(confirms=True, quote="X was deployed in the municipality")
    ctx = PhaseContext(store=store, llm=FakeLLM(verdict), skills=SkillRegistry("."))  # type: ignore[arg-type]

    result = CorroboratePhase(sid).run(ctx)

    assert "skipped" not in result.summary  # nothing is skipped anymore
    assert len(result.produced) == 2  # both c1 and c2 searched and confirmed


def test_corroborate_no_accepted_facts():
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text="text"))
    ctx = PhaseContext(
        store=store,
        llm=FakeLLM(Corroboration(confirms=False)),  # type: ignore[arg-type]
        skills=SkillRegistry("."),
    )
    assert CorroboratePhase(sid).run(ctx).ok is False
