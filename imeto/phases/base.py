"""Kontrakt fazy potoku (§5.1). Każda faza jest wymienna i testowalna w izolacji
(atrapa `llm`, tymczasowy `store`). Fazy zależą od rdzenia, nigdy odwrotnie."""

from dataclasses import dataclass, field
from typing import Protocol

from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore


@dataclass
class PhaseContext:
    store: ProvenanceStore
    llm: LLMClient
    # ponytail: tools/skills/dossier_id dołożyć, gdy powstaną rejestry (krok 10) —
    #           teraz byłyby martwymi polami.


@dataclass
class PhaseResult:
    ok: bool
    summary: str
    produced: list[int] = field(default_factory=list)  # id rekordów w provenance
    needs_human: bool = False  # czy wymaga przejścia przez próg


class Phase(Protocol):
    name: str

    def run(self, ctx: PhaseContext) -> PhaseResult: ...
