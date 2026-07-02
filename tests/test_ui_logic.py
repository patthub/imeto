from pathlib import Path

from docx import Document

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.registries.skills import SkillRegistry
from imeto.ui.app import apply_decisions, extract_candidates
from imeto.worktypes import WorkType


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


def _skills(tmp_path: Path) -> SkillRegistry:
    d = tmp_path / "knowledge" / "extraction" / "report"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("## Rola\nskill testowy", encoding="utf-8")
    return SkillRegistry(tmp_path / "knowledge")


def test_extract_candidates_returns_labeled_ids(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx")
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(
                statement="Rada przyjęła.", kind="direct", quotes=["uchwałę nr 12"]
            ),
            ExtractedFact(
                statement="Dotyczyło budżetu.",
                kind="inferred",
                quotes=["w sprawie budżetu"],
            ),
        ]
    )
    cands = extract_candidates(
        store, _skills(tmp_path), str(doc), WorkType.report, FakeLLM(ex)  # type: ignore[arg-type]
    )
    assert len(cands) == 2
    assert all(isinstance(cid, int) for cid, _ in cands)
    labels = " ".join(label for _, label in cands)
    assert "(direct)" in labels and "(inferred)" in labels
    assert "uchwałę nr 12" in labels


def test_apply_decisions_accepts_selected_rejects_rest():
    store = ProvenanceStore()
    src = Source(local_identifier="d", full_text="uchwałę nr 12 i tekst")
    sid = store.add_source(src)
    e1 = store.add_evidence(sid, "uchwałę nr 12")
    e2 = store.add_evidence(sid, "tekst")
    c1 = store.add_claim(sid, "a", "direct", [e1])
    c2 = store.add_claim(sid, "b", "direct", [e2])

    acc, rej = apply_decisions(store, [c1, c2], [c1])

    assert (acc, rej) == (1, 1)
    assert store.get_claim(c1).status == "accepted"
    assert store.get_claim(c2).status == "rejected"
    assert store.get_claim(c1).approved_by == "operator"
