import pytest

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import ExtractedFact

SRC = "Rada gminy przyjęła uchwałę nr 12 w sprawie budżetu."


def _store_with_candidate() -> tuple[ProvenanceStore, int, int]:
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text=SRC))
    eid = store.add_evidence(sid, ExtractedFact(quote="uchwałę nr 12", statement="x"))
    return store, sid, eid


def test_new_evidence_is_candidate():
    store, sid, _ = _store_with_candidate()
    (ev,) = store.evidence_for_source(sid)
    assert ev.status == "candidate"
    assert ev.decided_at is None


def test_accept_sets_status_and_author():
    store, sid, eid = _store_with_candidate()
    store.accept_evidence(eid, by="operator")
    ev = store.get_evidence(eid)
    assert ev.status == "accepted"
    assert ev.approved_by == "operator"
    assert ev.decided_at is not None


def test_reject_sets_status():
    store, sid, eid = _store_with_candidate()
    store.reject_evidence(eid, by="operator")
    assert store.get_evidence(eid).status == "rejected"


def test_filter_by_status():
    store, sid, eid = _store_with_candidate()
    store.add_evidence(sid, ExtractedFact(quote="w sprawie budżetu", statement="y"))
    store.accept_evidence(eid)
    assert len(store.evidence_for_source(sid, status="accepted")) == 1
    assert len(store.evidence_for_source(sid, status="candidate")) == 1
    assert len(store.evidence_for_source(sid)) == 2


def test_decide_unknown_raises():
    store, _, _ = _store_with_candidate()
    with pytest.raises(ValueError):
        store.accept_evidence(999)
