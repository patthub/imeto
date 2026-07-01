from pathlib import Path

from docx import Document

from imeto.core.provenance import ProvenanceStore
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.ui.app import apply_decisions, extract_candidates


class FakeLLM:
    model = "fake"

    def __init__(self, ex: Extraction) -> None:
        self._ex = ex

    def structured(
        self, system: str, user: str, schema: type[Extraction]
    ) -> Extraction:
        return self._ex


def _make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("Rada gminy przyjęła uchwałę nr 12 w sprawie budżetu.")
    doc.save(str(path))
    return path


def test_extract_candidates_returns_labeled_ids(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx")
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(quote="uchwałę nr 12", statement="Rada przyjęła."),
            ExtractedFact(quote="w sprawie budżetu", statement="Dot. budżetu."),
        ]
    )
    cands = extract_candidates(store, str(doc), FakeLLM(ex))  # type: ignore[arg-type]
    assert len(cands) == 2
    assert all(isinstance(eid, int) for eid, _ in cands)
    assert "Rada przyjęła." in cands[0][1]


def test_apply_decisions_accepts_selected_rejects_rest():
    from imeto.core.provenance import Source

    store = ProvenanceStore()
    src = Source(local_identifier="d", full_text="uchwałę nr 12 i tekst")
    sid = store.add_source(src)
    e1 = store.add_evidence(sid, ExtractedFact(quote="uchwałę nr 12", statement="a"))
    e2 = store.add_evidence(sid, ExtractedFact(quote="tekst", statement="b"))

    acc, rej = apply_decisions(store, [e1, e2], [e1])

    assert (acc, rej) == (1, 1)
    assert store.get_evidence(e1).status == "accepted"
    assert store.get_evidence(e2).status == "rejected"
    assert store.get_evidence(e1).approved_by == "operator"
