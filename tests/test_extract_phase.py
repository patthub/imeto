from pathlib import Path

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.phases.base import PhaseContext
from imeto.phases.extract import ExtractPhase
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType

TEXT = (
    "Rada gminy przyjęła uchwałę nr 12 w sprawie budżetu.\n"
    "Zorganizowano 3 konferencje naukowe.\n"
    "Każda konferencja zgromadziła po 100 osób."
)


class FakeLLM:
    model = "fake-model"

    def __init__(self, extraction: Extraction) -> None:
        self._ex = extraction

    def structured(
        self, system: str, user: str, schema: type[Extraction]
    ) -> Extraction:
        return self._ex


def _skills(tmp_path: Path) -> SkillRegistry:
    d = tmp_path / "knowledge" / "extraction" / "report"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("## Rola\nskill testowy", encoding="utf-8")
    return SkillRegistry(tmp_path / "knowledge")


def _ctx(
    store: ProvenanceStore, extraction: Extraction, tmp_path: Path
) -> PhaseContext:
    return PhaseContext(
        store=store,
        llm=FakeLLM(extraction),  # type: ignore[arg-type]
        skills=_skills(tmp_path),
    )


def _extraction() -> Extraction:
    return Extraction(
        facts=[
            ExtractedFact(
                statement="Rada przyjęła uchwałę budżetową.",
                kind="direct",
                quotes=["przyjęła uchwałę nr 12"],
            ),
            ExtractedFact(
                statement="Konferencje objęły ok. 300 osób.",
                kind="inferred",
                quotes=["3 konferencje", "po 100 osób"],
            ),
            ExtractedFact(
                statement="Rozwiązano radę nadzorczą.",
                kind="direct",
                quotes=["rozwiązano radę nadzorczą"],
            ),
            ExtractedFact(
                statement="Rada gminy działała.",
                kind="direct",
                quotes=["Rada gminy", "całkowicie zmyślony fragment"],
            ),
        ]
    )


def test_extract_typed_facts_with_grounds(tmp_path: Path):
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text=TEXT))
    ctx = _ctx(store, _extraction(), tmp_path)

    result = ExtractPhase(sid, WorkType.report).run(ctx)

    assert result.needs_human is True
    # 3 zapisane (direct, inferred, częściowy), 1 odrzucony (halucynacja)
    assert len(result.produced) == 3
    assert "1 odrzuconych" in result.summary
    assert "1 częściowych" in result.summary

    claims = store.claims_for_source(sid)
    assert sorted(c.kind for c in claims) == ["direct", "direct", "inferred"]

    inferred = next(c for c in claims if c.kind == "inferred")
    assert len(store.evidence_for_claim(inferred.id)) == 2
    assert all("Rozwiązano" not in c.statement for c in claims)


def test_empty_facts_produces_nothing(tmp_path: Path):
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text=TEXT))
    ctx = _ctx(store, Extraction(facts=[]), tmp_path)
    result = ExtractPhase(sid, WorkType.report).run(ctx)
    assert result.produced == []


def test_phase_name():
    assert ExtractPhase(1, WorkType.report).name == "extract"
