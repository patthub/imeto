import pytest

from imeto.core.provenance import ProvenanceStore, Source, SpanNotVerified
from imeto.core.schemas import ExtractedFact

SRC_TEXT = "Rada gminy przyjęła uchwałę nr 12\nw sprawie budżetu na rok 2025."


def make_store() -> ProvenanceStore:
    return ProvenanceStore()  # domyślnie SQLite in-memory


def add_src(store: ProvenanceStore, text: str = SRC_TEXT) -> int:
    return store.add_source(Source(local_identifier="doc:1", full_text=text))


def test_add_evidence_verified_stores_offsets():
    store = make_store()
    sid = add_src(store)
    eid = store.add_evidence(
        sid, ExtractedFact(quote="przyjęła uchwałę nr 12", statement="Rada przyjęła.")
    )
    (ev,) = store.evidence_for_source(sid)
    assert ev.id == eid
    assert SRC_TEXT[ev.start : ev.end] == "przyjęła uchwałę nr 12"


def test_add_evidence_whitespace_collapsed_anchors_original():
    store = make_store()
    sid = add_src(store)
    store.add_evidence(
        sid, ExtractedFact(quote="nr 12 w sprawie budżetu", statement="x")
    )
    (ev,) = store.evidence_for_source(sid)
    # offsety wskazują oryginał z newline, nie zwiniętą wersję z cytatu
    assert SRC_TEXT[ev.start : ev.end] == "nr 12\nw sprawie budżetu"


def test_unverifiable_quote_is_rejected():
    store = make_store()
    sid = add_src(store)
    with pytest.raises(SpanNotVerified):
        store.add_evidence(
            sid, ExtractedFact(quote="przyjęła uchwałę nr 13", statement="halucynacja")
        )
    assert store.evidence_for_source(sid) == []  # nic nie zapisane


def test_unknown_source_rejected():
    store = make_store()
    with pytest.raises(ValueError):
        store.add_evidence(999, ExtractedFact(quote="x", statement="y"))


def test_provenance_fields_persist():
    store = make_store()
    sid = add_src(store)
    store.add_evidence(
        sid,
        ExtractedFact(quote="uchwałę nr 12", statement="x"),
        activity="extract-run-1",
        agent="model:qwen-3b",
    )
    (ev,) = store.evidence_for_source(sid)
    assert ev.generated_by_activity == "extract-run-1"
    assert ev.attributed_to_agent == "model:qwen-3b"
    assert ev.generated_at_time is not None


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
    ev = store.get_source(sid)
    assert ev.identifiers == [{"scheme": "doi", "value": "10.1234/x"}]
    assert ev.fabio_type.endswith("JournalArticle")


def test_verify_span_audit():
    store = make_store()
    sid = add_src(store)
    eid = store.add_evidence(sid, ExtractedFact(quote="uchwałę nr 12", statement="x"))
    assert store.verify_span(sid, eid) is True


def test_evidence_isolated_per_source():
    store = make_store()
    s1 = store.add_source(Source(local_identifier="a", full_text=SRC_TEXT))
    s2 = store.add_source(Source(local_identifier="b", full_text=SRC_TEXT))
    store.add_evidence(s1, ExtractedFact(quote="uchwałę nr 12", statement="x"))
    assert len(store.evidence_for_source(s1)) == 1
    assert store.evidence_for_source(s2) == []
