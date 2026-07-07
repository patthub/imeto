import pytest

from imeto.core.provenance import ProvenanceStore, Source, SpanNotVerified

SRC_TEXT = "Rada gminy przyjęła uchwałę nr 12\nw sprawie budżetu na rok 2025."


def make_store() -> ProvenanceStore:
    return ProvenanceStore()  # domyślnie SQLite in-memory


def add_src(store: ProvenanceStore, text: str = SRC_TEXT) -> int:
    return store.add_source(Source(local_identifier="doc:1", full_text=text))


def test_add_evidence_verified_stores_offsets():
    store = make_store()
    sid = add_src(store)
    eid = store.add_evidence(sid, "przyjęła uchwałę nr 12")
    ev = store.get_evidence(eid)
    assert SRC_TEXT[ev.start : ev.end] == "przyjęła uchwałę nr 12"


def test_add_evidence_whitespace_collapsed_anchors_original():
    store = make_store()
    sid = add_src(store)
    eid = store.add_evidence(sid, "nr 12 w sprawie budżetu")
    ev = store.get_evidence(eid)
    assert SRC_TEXT[ev.start : ev.end] == "nr 12\nw sprawie budżetu"


def test_unverifiable_quote_is_rejected():
    store = make_store()
    sid = add_src(store)
    with pytest.raises(SpanNotVerified):
        store.add_evidence(sid, "przyjęła uchwałę nr 13")
    assert store.evidence_for_source(sid) == []


def test_unknown_source_rejected():
    store = make_store()
    with pytest.raises(ValueError):
        store.add_evidence(999, "cokolwiek")


def test_add_claim_links_grounds():
    store = make_store()
    sid = add_src(store)
    e1 = store.add_evidence(sid, "uchwałę nr 12")
    e2 = store.add_evidence(sid, "w sprawie budżetu")
    cid = store.add_claim(sid, "Rada przyjęła uchwałę budżetową.", "inferred", [e1, e2])

    claim = store.get_claim(cid)
    assert claim.kind == "inferred"
    grounds = store.evidence_for_claim(cid)
    assert {g.id for g in grounds} == {e1, e2}


def test_add_claim_requires_at_least_one_ground():
    store = make_store()
    sid = add_src(store)
    with pytest.raises(ValueError):
        store.add_claim(sid, "fakt bez gruntu", "direct", [])


def test_claims_filter_by_status():
    store = make_store()
    sid = add_src(store)
    e = store.add_evidence(sid, "uchwałę nr 12")
    c1 = store.add_claim(sid, "a", "direct", [e])
    store.add_claim(sid, "b", "direct", [e])
    store.accept_claim(c1)
    assert len(store.claims_for_source(sid, status="accepted")) == 1
    assert len(store.claims_for_source(sid, status="candidate")) == 1
    assert len(store.claims_for_source(sid)) == 2


def test_provenance_and_kind_persist():
    store = make_store()
    sid = add_src(store)
    e = store.add_evidence(sid, "uchwałę nr 12", activity="run-1", agent="m")
    cid = store.add_claim(sid, "x", "direct", [e], activity="run-1", agent="m")
    claim = store.get_claim(cid)
    assert claim.generated_by_activity == "run-1"
    assert claim.attributed_to_agent == "m"
    assert store.get_evidence(e).attributed_to_agent == "m"


def test_source_identifiers_roundtrip():
    store = make_store()
    sid = store.add_source(
        Source(
            local_identifier="doi:10.1234/x",
            full_text=SRC_TEXT,
            fabio_type="http://purl.org/spar/fabio/JournalArticle",
            identifiers=[{"scheme": "doi", "value": "10.1234/x"}],
        )
    )
    src = store.get_source(sid)
    assert src.identifiers == [{"scheme": "doi", "value": "10.1234/x"}]
    assert src.fabio_type.endswith("JournalArticle")


def test_verify_span_audit():
    store = make_store()
    sid = add_src(store)
    eid = store.add_evidence(sid, "uchwałę nr 12")
    assert store.verify_span(sid, eid) is True


def test_argument_links_claims_and_gate():
    store = make_store()
    sid = add_src(store)
    e = store.add_evidence(sid, "uchwałę nr 12")
    c1 = store.add_claim(sid, "fakt a", "direct", [e])
    c2 = store.add_claim(sid, "fakt b", "direct", [e])

    aid = store.add_argument(sid, "kryterium_iii", "za", "argument", [c1, c2])
    assert store.get_argument(aid).side == "za"
    assert {c.id for c in store.claims_for_argument(aid)} == {c1, c2}

    store.accept_argument(aid, by="ekspert")
    arg = store.get_argument(aid)
    assert arg.status == "accepted" and arg.approved_by == "ekspert"
    assert len(store.arguments_for_source(sid, status="accepted")) == 1


def test_argument_may_have_no_claims_for_gap():
    store = make_store()
    sid = add_src(store)
    aid = store.add_argument(sid, "kryterium_iii", "luka", "brak dowodu", [])
    assert store.claims_for_argument(aid) == []
