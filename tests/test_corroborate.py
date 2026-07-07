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
    src = Source(local_identifier="doc", full_text="Opublikowano pilotaż.")
    sid = store.add_source(src)
    e = store.add_evidence(sid, "Opublikowano pilotaż")
    c = store.add_claim(sid, "Opublikowano pilotaż.", "direct", [e])
    store.accept_claim(c)
    return sid, c


def _mock_search_fetch(monkeypatch: pytest.MonkeyPatch, page_text: str) -> None:
    hit = [SearchResult("t", "https://gov.pl/x", "s")]
    monkeypatch.setattr(C, "web_search", lambda q, max_results=3: hit)
    monkeypatch.setattr(C, "fetch_url_text", lambda url: page_text)


def test_corroborate_anchors_external_confirmation(monkeypatch: pytest.MonkeyPatch):
    store = ProvenanceStore()
    sid, c = _one_accepted_fact(store)
    _mock_search_fetch(monkeypatch, "Pilotaż został oficjalnie wdrożony w 2025 roku.")
    verdict = Corroboration(confirms=True, quote="Pilotaż został oficjalnie wdrożony")
    ctx = PhaseContext(store=store, llm=FakeLLM(verdict), skills=SkillRegistry("."))  # type: ignore[arg-type]

    result = CorroboratePhase(sid).run(ctx)

    assert len(result.produced) == 1
    ev = store.get_evidence(result.produced[0])
    # dowód pochodzi z ZEWNĘTRZNEJ strony i jest wpięty do faktu
    assert store.get_source(ev.source_id).local_identifier == "https://gov.pl/x"
    linked = store.evidence_for_claim(c)
    assert any(x.source_id != sid for x in linked)  # zewnętrzne potwierdzenie wpięte


def test_corroborate_rejects_non_verbatim_quote(monkeypatch: pytest.MonkeyPatch):
    store = ProvenanceStore()
    sid, c = _one_accepted_fact(store)
    _mock_search_fetch(monkeypatch, "Strona o zupełnie czymś innym.")
    verdict = Corroboration(confirms=True, quote="zmyślony cytat, którego nie ma")
    ctx = PhaseContext(store=store, llm=FakeLLM(verdict), skills=SkillRegistry("."))  # type: ignore[arg-type]

    result = CorroboratePhase(sid).run(ctx)
    assert result.produced == []  # cytat nie występuje dosłownie -> odrzucony


def test_corroborate_confirms_false_skips(monkeypatch: pytest.MonkeyPatch):
    store = ProvenanceStore()
    sid, _ = _one_accepted_fact(store)
    _mock_search_fetch(monkeypatch, "Pilotaż został oficjalnie wdrożony.")
    verdict = Corroboration(confirms=False, quote="")
    ctx = PhaseContext(store=store, llm=FakeLLM(verdict), skills=SkillRegistry("."))  # type: ignore[arg-type]
    assert CorroboratePhase(sid).run(ctx).produced == []


def test_corroborate_no_accepted_facts():
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text="tekst"))
    ctx = PhaseContext(
        store=store,
        llm=FakeLLM(Corroboration(confirms=False)),  # type: ignore[arg-type]
        skills=SkillRegistry("."),
    )
    assert CorroboratePhase(sid).run(ctx).ok is False
