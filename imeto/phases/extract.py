"""Faza ekstrakcji (POC-1): dokument → fakty poparte dosłownym cytatem.

Pierwszy pełny przepływ: parsing → LLM → weryfikacja spanu → provenance. Fakty,
których cytat nie ma pokrycia w źródle, są ODRZUCANE (SpanNotVerified) i nie trafiają
do bazy — to egzekucja niezmiennika anty-halucynacji na poziomie fazy."""

from dataclasses import dataclass, field
from pathlib import Path

from imeto.core.provenance import Source, SpanNotVerified
from imeto.core.schemas import Extraction
from imeto.ingest.parsing import parse_document
from imeto.phases.base import PhaseContext, PhaseResult

EXTRACT_SYSTEM = (
    "Jesteś asystentem wydobywającym fakty ze sprawozdań. Zwróć wyłącznie JSON w "
    'formacie: {"facts": [{"quote": "...", "statement": "..."}]}\n'
    "- quote MUSI być dosłownym fragmentem tekstu, skopiowanym znak w znak.\n"
    "- statement to fakt, który ten cytat popiera (własnymi słowami, zwięźle).\n"
    "- Nie zmyślaj cytatów. Jeśli fragmentu nie ma w tekście, nie dodawaj go.\n"
    "- Jeśli nie znajdziesz żadnych faktów, zwróć {\"facts\": []}."
)


@dataclass
class ExtractPhase:
    document: Path
    name: str = field(default="extract")

    def run(self, ctx: PhaseContext) -> PhaseResult:
        text = parse_document(self.document)
        source_id = ctx.store.add_source(
            Source(local_identifier=str(self.document), full_text=text)
        )
        extraction = ctx.llm.structured(EXTRACT_SYSTEM, text, Extraction)

        activity = f"extract:{source_id}"
        produced: list[int] = []
        rejected = 0
        for fact in extraction.facts:
            try:
                eid = ctx.store.add_evidence(
                    source_id, fact, activity=activity, agent=ctx.llm.model
                )
                produced.append(eid)
            except SpanNotVerified:
                rejected += 1  # cytat bez pokrycia — halucynacja, pomijamy

        summary = (
            f"źródło {source_id}: {len(produced)} kandydatów zapisanych, "
            f"{rejected} odrzuconych (cytat bez pokrycia w źródle)"
        )
        return PhaseResult(
            ok=True, summary=summary, produced=produced, needs_human=True
        )
