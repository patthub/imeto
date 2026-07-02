from pathlib import Path

from docx import Document

from imeto.core.provenance import ProvenanceStore
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.phases.base import PhaseContext
from imeto.phases.extract import ExtractPhase
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType


class FakeLLM:
    model = "fake-model"

    def __init__(self, extraction: Extraction) -> None:
        self._ex = extraction

    def structured(
        self, system: str, user: str, schema: type[Extraction]
    ) -> Extraction:
        return self._ex


def _skills(tmp_path: Path) -> SkillRegistry:
    d = tmp_path / "knowledge" / "extraction"
    d.mkdir(parents=True)
    (d / "report.md").write_text("skill testowy", encoding="utf-8")
    return SkillRegistry(tmp_path / "knowledge")


def _make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("Rada gminy przyjęła uchwałę nr 12 w sprawie budżetu.")
    doc.add_paragraph("Zorganizowano 3 konferencje naukowe.")
    doc.add_paragraph("Każda konferencja zgromadziła po 100 osób.")
    doc.save(str(path))
    return path


def _extraction() -> Extraction:
    return Extraction(
        facts=[
            # direct — grunt weryfikuje się
            ExtractedFact(
                statement="Rada przyjęła uchwałę budżetową.",
                kind="direct",
                quotes=["przyjęła uchwałę nr 12"],
            ),
            # inferred — dwie przesłanki, obie się weryfikują
            ExtractedFact(
                statement="Konferencje objęły ok. 300 osób.",
                kind="inferred",
                quotes=["3 konferencje", "po 100 osób"],
            ),
            # halucynacja — żaden grunt nie istnieje → odrzucone
            ExtractedFact(
                statement="Rozwiązano radę nadzorczą.",
                kind="direct",
                quotes=["rozwiązano radę nadzorczą"],
            ),
            # częściowy — jeden grunt ok, drugi zmyślony
            ExtractedFact(
                statement="Rada gminy działała.",
                kind="direct",
                quotes=["Rada gminy", "całkowicie zmyślony fragment"],
            ),
        ]
    )


def test_extract_typed_facts_with_grounds(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx")
    store = ProvenanceStore()
    ctx = PhaseContext(
        store=store,
        llm=FakeLLM(_extraction()),  # type: ignore[arg-type]
        skills=_skills(tmp_path),
    )

    result = ExtractPhase(doc, WorkType.report).run(ctx)

    assert result.needs_human is True
    # 3 zapisane (direct, inferred, częściowy), 1 odrzucony (halucynacja)
    assert len(result.produced) == 3
    assert "1 odrzuconych" in result.summary
    assert "1 częściowych" in result.summary

    claims = store.claims_for_source(1)
    kinds = sorted(c.kind for c in claims)
    assert kinds == ["direct", "direct", "inferred"]

    # fakt wywnioskowany ma dwa zakotwiczone grunty
    inferred = next(c for c in claims if c.kind == "inferred")
    assert len(store.evidence_for_claim(inferred.id)) == 2

    # halucynacja nie zostawiła śladu w faktach
    assert all("Rozwiązano" not in c.statement for c in claims)


def test_empty_facts_produces_nothing(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx")
    store = ProvenanceStore()
    ctx = PhaseContext(
        store=store,
        llm=FakeLLM(Extraction(facts=[])),  # type: ignore[arg-type]
        skills=_skills(tmp_path),
    )
    result = ExtractPhase(doc, WorkType.report).run(ctx)
    assert result.produced == []


def test_phase_name():
    assert ExtractPhase(Path("x.docx"), WorkType.report).name == "extract"
