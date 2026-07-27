from pathlib import Path

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.phases.base import PhaseContext
from imeto.phases.extract import ExtractPhase, _dedup_facts
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType


class ChunkAwareLLM:
    """Stub returning a given fact only for the chunk that contains its quote."""

    model = "fake"

    def __init__(self, candidates: list[ExtractedFact]) -> None:
        self._c = candidates

    def structured(
        self, system: str, user: str, schema: type[Extraction]
    ) -> Extraction:
        matched = [f for f in self._c if all(q in user for q in f.quotes)]
        return Extraction(facts=matched)


TEXT = (
    "The council adopted resolution no. 12 regarding the budget.\n"
    "3 scientific conferences were organized.\n"
    "Each conference gathered 100 people."
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
    (d / "SKILL.md").write_text("## Role\ntest skill", encoding="utf-8")
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
                statement="The council adopted a budget resolution.",
                kind="direct",
                quotes=["adopted resolution no. 12"],
            ),
            ExtractedFact(
                statement="The conferences covered about 300 people.",
                kind="inferred",
                quotes=["3 scientific conferences", "100 people"],
            ),
            ExtractedFact(
                statement="The supervisory board was dissolved.",
                kind="direct",
                quotes=["the supervisory board was dissolved"],
            ),
            ExtractedFact(
                statement="The council was active.",
                kind="direct",
                quotes=["The council", "a completely fabricated fragment"],
            ),
        ]
    )


def test_extract_typed_facts_with_grounds(tmp_path: Path):
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text=TEXT))
    ctx = _ctx(store, _extraction(), tmp_path)

    result = ExtractPhase(sid, WorkType.report).run(ctx)

    assert result.needs_human is True
    # 3 saved (direct, inferred, partial), 1 rejected (hallucination)
    assert len(result.produced) == 3
    assert "1 rejected" in result.summary
    assert "1 partial" in result.summary

    claims = store.claims_for_source(sid)
    assert sorted(c.kind for c in claims) == ["direct", "direct", "inferred"]

    inferred = next(c for c in claims if c.kind == "inferred")
    assert len(store.evidence_for_claim(inferred.id)) == 2
    assert all("dissolved" not in c.statement for c in claims)


def test_empty_facts_produces_nothing(tmp_path: Path):
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text=TEXT))
    ctx = _ctx(store, Extraction(facts=[]), tmp_path)
    result = ExtractPhase(sid, WorkType.report).run(ctx)
    assert result.produced == []


def test_phase_name():
    assert ExtractPhase(1, WorkType.report).name == "extract"


def test_dedup_facts_by_quote_set():
    f1 = ExtractedFact(statement="a", kind="direct", quotes=["X snippet"])
    f2 = ExtractedFact(statement="a differently", kind="direct", quotes=["X snippet"])
    f3 = ExtractedFact(statement="b", kind="direct", quotes=["Y snippet"])
    out = _dedup_facts([f1, f2, f3])
    assert len(out) == 2  # f2 (same quotes) removed


def test_extract_over_chunks_collects_facts_from_all(tmp_path: Path):
    # text longer than chunk_chars: ALFA at the start, BETA at the end
    filler = "filler line of text.\n" * 30
    text = "ALFA first fact.\n" + filler + "BETA second fact."
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text=text))
    candidates = [
        ExtractedFact(statement="1", kind="direct", quotes=["ALFA first fact"]),
        ExtractedFact(statement="2", kind="direct", quotes=["BETA second fact"]),
    ]
    ctx = PhaseContext(
        store=store,
        llm=ChunkAwareLLM(candidates),  # type: ignore[arg-type]
        skills=_skills(tmp_path),
    )

    result = ExtractPhase(sid, WorkType.report, chunk_chars=100).run(ctx)

    assert "chunks" in result.summary  # the text was split
    claims = store.claims_for_source(sid)
    quotes = {ev.quote for c in claims for ev in store.evidence_for_claim(c.id)}
    assert "ALFA first fact" in quotes
    assert "BETA second fact" in quotes


class FailingChunkLLM:
    """Raises for the chunk with FAILHERE, returns a fact for the chunk with GOOD."""

    model = "fake"

    def structured(
        self, system: str, user: str, schema: type[Extraction]
    ) -> Extraction:
        if "FAILHERE" in user:
            raise RuntimeError("simulated chunk failure")
        if "GOOD fact" in user:
            fact = ExtractedFact(statement="ok", kind="direct", quotes=["GOOD fact"])
            return Extraction(facts=[fact])
        return Extraction(facts=[])


def test_chunk_failure_does_not_lose_other_facts(tmp_path: Path):
    filler = "filler line of text.\n" * 30
    text = "GOOD fact here.\n" + filler + "FAILHERE end."
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text=text))
    ctx = PhaseContext(
        store=store,
        llm=FailingChunkLLM(),  # type: ignore[arg-type]
        skills=_skills(tmp_path),
    )

    result = ExtractPhase(sid, WorkType.report, chunk_chars=100).run(ctx)

    assert len(store.claims_for_source(sid)) == 1  # fact from the good chunk survived
    assert "failed" in result.summary
