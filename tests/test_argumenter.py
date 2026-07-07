from pathlib import Path

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import Argumentation, ProposedArgument
from imeto.phases.argumenter import ArgumenterPhase
from imeto.phases.base import PhaseContext
from imeto.registries.skills import SkillRegistry


class FakeArgLLM:
    model = "fake"

    def __init__(self, argumentation: Argumentation) -> None:
        self._a = argumentation

    def structured(
        self, system: str, user: str, schema: type[Argumentation]
    ) -> Argumentation:
        return self._a


def _criteria_skills(tmp_path: Path) -> SkillRegistry:
    d = tmp_path / "knowledge" / "criteria" / "kryterium_iii"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("## Rubryka\ntest", encoding="utf-8")
    return SkillRegistry(tmp_path / "knowledge")


def _two_accepted_claims(store: ProvenanceStore) -> int:
    text = "Wdrożono system X. System poprawił zdrowie pacjentów."
    sid = store.add_source(Source(local_identifier="d", full_text=text))
    e1 = store.add_evidence(sid, "Wdrożono system X")
    e2 = store.add_evidence(sid, "poprawił zdrowie pacjentów")
    c1 = store.add_claim(sid, "Wdrożono system X.", "direct", [e1])
    c2 = store.add_claim(sid, "System poprawił zdrowie.", "direct", [e2])
    store.accept_claim(c1)
    store.accept_claim(c2)
    return sid


def test_argue_grounds_and_gates(tmp_path: Path):
    store = ProvenanceStore()
    sid = _two_accepted_claims(store)
    arg = Argumentation(
        arguments=[
            ProposedArgument(
                side="za", statement="Wdrożenie z korzyścią zdrowotną.", based_on=[1, 2]
            ),
            ProposedArgument(side="przeciw", statement="bez oparcia", based_on=[]),
            ProposedArgument(side="luka", statement="brak danych", based_on=[]),
            ProposedArgument(side="za", statement="zmyślone", based_on=[99]),
        ]
    )
    ctx = PhaseContext(
        store=store, llm=FakeArgLLM(arg), skills=_criteria_skills(tmp_path)  # type: ignore[arg-type]
    )

    result = ArgumenterPhase(sid, "kryterium_iii").run(ctx)

    assert result.ok is True and result.needs_human is True
    # zapisane: ZA(oparty) + LUKA(pusta ok); odrzucone: PRZECIW pusty, ZA z błędnym idx
    assert len(result.produced) == 2
    assert "1 ZA" in result.summary
    assert "1 LUKI" in result.summary
    assert "2 odrzuconych" in result.summary
    za = next(
        store.get_argument(a)
        for a in result.produced
        if store.get_argument(a).side == "za"
    )
    assert len(store.claims_for_argument(za.id)) == 2  # oparty o oba fakty


def test_argue_no_accepted_claims_is_not_ok(tmp_path: Path):
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text="tekst"))
    ctx = PhaseContext(
        store=store,
        llm=FakeArgLLM(Argumentation(arguments=[])),  # type: ignore[arg-type]
        skills=_criteria_skills(tmp_path),
    )
    result = ArgumenterPhase(sid, "kryterium_iii").run(ctx)
    assert result.ok is False
    assert "brak faktów" in result.summary
