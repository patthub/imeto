from pathlib import Path

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import Argumentation, ProposedArgument
from imeto.phases.argumenter import ArgumenterPhase, _facts_text
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
    (d / "SKILL.md").write_text("## Rubric\ntest", encoding="utf-8")
    return SkillRegistry(tmp_path / "knowledge")


def _two_accepted_claims(store: ProvenanceStore) -> int:
    text = "System X was deployed. The system improved patient health."
    sid = store.add_source(Source(local_identifier="d", full_text=text))
    e1 = store.add_evidence(sid, "System X was deployed")
    e2 = store.add_evidence(sid, "improved patient health")
    c1 = store.add_claim(sid, "System X was deployed.", "direct", [e1])
    c2 = store.add_claim(sid, "The system improved health.", "direct", [e2])
    store.accept_claim(c1)
    store.accept_claim(c2)
    return sid


def test_argue_grounds_and_gates(tmp_path: Path):
    store = ProvenanceStore()
    sid = _two_accepted_claims(store)
    arg = Argumentation(
        arguments=[
            ProposedArgument(
                side="for", statement="Deployment with health benefit.", based_on=[1, 2]
            ),
            ProposedArgument(side="against", statement="no grounding", based_on=[]),
            ProposedArgument(side="gap", statement="no data", based_on=[]),
            ProposedArgument(side="for", statement="fabricated", based_on=[99]),
        ]
    )
    ctx = PhaseContext(
        store=store,
        llm=FakeArgLLM(arg),
        skills=_criteria_skills(tmp_path),  # type: ignore[arg-type]
    )

    result = ArgumenterPhase(sid, "kryterium_iii").run(ctx)

    assert result.ok is True and result.needs_human is True
    # saved: FOR(grounded) + GAP(empty ok); rejected: AGAINST empty, FOR with bad idx
    assert len(result.produced) == 2
    assert "1 FOR" in result.summary
    assert "1 GAPS" in result.summary
    assert "2 rejected" in result.summary
    for_arg = next(
        store.get_argument(a)
        for a in result.produced
        if store.get_argument(a).side == "for"
    )
    assert len(store.claims_for_argument(for_arg.id)) == 2  # grounded on both facts


def test_facts_text_marks_external_corroboration(tmp_path: Path):
    # dossier: a fact corroborated externally (grounding from another source) → marker
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="doc", full_text="X was deployed."))
    e = store.add_evidence(sid, "X was deployed")
    c = store.add_claim(sid, "X was deployed.", "direct", [e])
    ext = store.add_source(
        Source(
            local_identifier="https://gov.pl/p",
            full_text="X works in the municipality.",
        )
    )
    ee = store.add_evidence(ext, "X works in the municipality")
    store.link_evidence(c, ee)
    ctx = PhaseContext(
        store=store,
        llm=FakeArgLLM(Argumentation(arguments=[])),  # type: ignore[arg-type]
        skills=_criteria_skills(tmp_path),
    )

    text = _facts_text(ctx, store.claims_for_source(sid))

    assert "✓CONFIRMED" in text
    assert "„X works in the municipality” — https://gov.pl/p" in text
    assert store.external_evidence_for_claim(c)[0].source_id == ext


def test_argue_no_accepted_claims_is_not_ok(tmp_path: Path):
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text="text"))
    ctx = PhaseContext(
        store=store,
        llm=FakeArgLLM(Argumentation(arguments=[])),  # type: ignore[arg-type]
        skills=_criteria_skills(tmp_path),
    )
    result = ArgumenterPhase(sid, "kryterium_iii").run(ctx)
    assert result.ok is False
    assert "no facts" in result.summary


def test_argument_keeps_the_proposed_sphere_and_the_human_can_change_it(
    tmp_path: Path,
):
    store = ProvenanceStore()
    sid = _two_accepted_claims(store)
    arg = Argumentation(
        arguments=[
            ProposedArgument(
                side="for", statement="Better care.", based_on=[2], sphere="health"
            )
        ]
    )
    ctx = PhaseContext(
        store=store,
        llm=FakeArgLLM(arg),
        skills=_criteria_skills(tmp_path),  # type: ignore[arg-type]
    )
    (aid,) = ArgumenterPhase(sid).run(ctx).produced
    assert store.get_argument(aid).sphere == "health"
    store.set_argument_sphere(aid, "public_administration")
    assert store.get_argument(aid).sphere == "public_administration"
