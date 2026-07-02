import pytest

from imeto.core.provenance import ProvenanceStore, Source

SRC = "Rada gminy przyjęła uchwałę nr 12 w sprawie budżetu."


def _store_with_claim() -> tuple[ProvenanceStore, int, int]:
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text=SRC))
    e = store.add_evidence(sid, "uchwałę nr 12")
    cid = store.add_claim(sid, "Rada przyjęła.", "direct", [e])
    return store, sid, cid


def test_new_claim_is_candidate():
    store, _, cid = _store_with_claim()
    claim = store.get_claim(cid)
    assert claim.status == "candidate"
    assert claim.decided_at is None


def test_accept_sets_status_and_author():
    store, _, cid = _store_with_claim()
    store.accept_claim(cid, by="operator")
    claim = store.get_claim(cid)
    assert claim.status == "accepted"
    assert claim.approved_by == "operator"
    assert claim.decided_at is not None


def test_reject_sets_status():
    store, _, cid = _store_with_claim()
    store.reject_claim(cid, by="operator")
    assert store.get_claim(cid).status == "rejected"


def test_decide_unknown_raises():
    store, _, _ = _store_with_claim()
    with pytest.raises(ValueError):
        store.accept_claim(999)
