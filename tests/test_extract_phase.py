from pathlib import Path

from docx import Document

from imeto.core.provenance import ProvenanceStore
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.phases.base import PhaseContext
from imeto.phases.extract import ExtractPhase


class FakeLLM:
    """Atrapa klienta LLM — zwraca ustaloną ekstrakcję bez sieci."""

    model = "fake-model"

    def __init__(self, extraction: Extraction) -> None:
        self._ex = extraction

    def structured(
        self, system: str, user: str, schema: type[Extraction]
    ) -> Extraction:
        return self._ex


def _make_docx(path: Path, text: str) -> Path:
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))
    return path


def test_extract_stores_verified_and_drops_hallucinated(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx", "Rada gminy przyjęła uchwałę nr 12.")
    store = ProvenanceStore()
    fake = FakeLLM(
        Extraction(
            facts=[
                ExtractedFact(quote="przyjęła uchwałę nr 12", statement="Rada."),
                ExtractedFact(quote="rozwiązała radę nadzorczą", statement="zmyślone"),
            ]
        )
    )
    ctx = PhaseContext(store=store, llm=fake)  # type: ignore[arg-type]

    result = ExtractPhase(doc).run(ctx)

    assert result.ok is True
    assert result.needs_human is True
    assert len(result.produced) == 1  # tylko dowód z pokryciem
    assert "1 kandydatów" in result.summary and "1 odrzuconych" in result.summary

    # zapisany dowód kotwiczy się w źródle, z pochodzeniem
    (ev,) = store.evidence_for_source(1)
    assert ev.quote == "przyjęła uchwałę nr 12"
    assert ev.attributed_to_agent == "fake-model"
    assert ev.generated_by_activity == "extract:1"


def test_extract_empty_facts_produces_nothing(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx", "Nic istotnego.")
    store = ProvenanceStore()
    ctx = PhaseContext(store=store, llm=FakeLLM(Extraction(facts=[])))  # type: ignore[arg-type]
    result = ExtractPhase(doc).run(ctx)
    assert result.produced == []
    assert result.ok is True


def test_phase_name():
    assert ExtractPhase(Path("x.docx")).name == "extract"
