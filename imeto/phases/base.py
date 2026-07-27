"""Pipeline phase contract (§5.1). Every phase is swappable and testable in isolation
(a mock `llm`, a temporary `store`). Phases depend on the core, never the reverse."""

from dataclasses import dataclass, field
from typing import Protocol

from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore
from imeto.registries.skills import SkillRegistry


@dataclass
class PhaseContext:
    store: ProvenanceStore
    llm: LLMClient
    skills: SkillRegistry
    # ponytail: add tools/dossier_id once they exist (ToolRegistry, state machine) —
    #           right now they would be dead fields.


@dataclass
class PhaseResult:
    ok: bool
    summary: str
    produced: list[int] = field(default_factory=list)  # ids of provenance records
    needs_human: bool = False  # whether it must pass through the gate


class Phase(Protocol):
    name: str

    def run(self, ctx: PhaseContext) -> PhaseResult: ...
