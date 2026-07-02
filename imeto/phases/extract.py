"""Faza ekstrakcji: dokument → fakty (direct/inferred) z dosłownie zakotwiczonymi
gruntami.

Realizuje ustaloną zasadę:
- każdy grunt (cytat) weryfikowany dosłownie przez `add_evidence`,
- fakt bez ani jednego zweryfikowanego gruntu = halucynacja → ODRZUCANY (nie zapisany),
- fakt z >=1 gruntem zapisywany jako `Claim` z zachowanym `kind` (direct/inferred);
  brakujące grunty są zliczane (fakt „częściowy" — do uwagi człowieka),
- rodzaj faktu (wprost vs wywnioskowany) nigdy nie jest zlewany."""

from dataclasses import dataclass, field
from pathlib import Path

from imeto.core.provenance import Source, SpanNotVerified
from imeto.core.schemas import Extraction
from imeto.ingest.parsing import parse_document
from imeto.phases.base import PhaseContext, PhaseResult
from imeto.worktypes import FABIO, WorkType

EXTRACT_SYSTEM = (
    "Jesteś asystentem wydobywającym fakty z wytworów naukowych. Zwróć tylko JSON:\n"
    '{"facts": [{"statement": "...", "kind": "direct|inferred", '
    '"quotes": ["...", "..."]}]}\n'
    "- statement: fakt własnymi słowami, zwięźle.\n"
    '- kind: "direct" gdy fakt jest napisany w tekście wprost; '
    '"inferred" gdy go wywnioskowałeś z tekstu.\n'
    "- quotes: dosłowne fragmenty ŹRÓDŁA (skopiowane znak w znak), na których "
    'fakt się opiera. Dla "direct" to poparcie; dla "inferred" to PRZESŁANKI.\n'
    "- Każdy fakt MUSI mieć co najmniej jeden cytat. Nie zmyślaj cytatów: "
    "jeśli fragmentu nie ma w tekście, nie używaj go.\n"
    '- Jeśli nie znajdziesz faktów, zwróć {"facts": []}.'
)


@dataclass
class ExtractPhase:
    document: Path
    work_type: WorkType
    name: str = field(default="extract")

    def run(self, ctx: PhaseContext) -> PhaseResult:
        text = parse_document(self.document)
        source_id = ctx.store.add_source(
            Source(
                local_identifier=str(self.document),
                full_text=text,
                fabio_type=FABIO[self.work_type],
            )
        )
        # baza (uniwersalne niezmienniki) + skill typu wytworu (co jest faktem)
        skill = ctx.skills.load(self.work_type.value)
        system = f"{EXTRACT_SYSTEM}\n\n{skill}"
        extraction = ctx.llm.structured(system, text, Extraction)

        activity = f"extract:{source_id}"
        agent = ctx.llm.model
        produced: list[int] = []
        ungrounded = 0  # fakty bez żadnego zweryfikowanego gruntu (odrzucone)
        partial = 0  # fakty z częścią gruntów niezweryfikowanych (do uwagi człowieka)

        for fact in extraction.facts:
            ev_ids: list[int] = []
            failed = 0
            for quote in fact.quotes:
                try:
                    ev_ids.append(
                        ctx.store.add_evidence(
                            source_id, quote, activity=activity, agent=agent
                        )
                    )
                except SpanNotVerified:
                    failed += 1
            if not ev_ids:
                ungrounded += 1  # brak pokrycia w całości — halucynacja, pomijamy
                continue
            if failed:
                partial += 1
            claim_id = ctx.store.add_claim(
                source_id, fact.statement, fact.kind, ev_ids,
                activity=activity, agent=agent,
            )
            produced.append(claim_id)

        summary = (
            f"źródło {source_id}: {len(produced)} faktów zapisanych "
            f"({partial} częściowych), {ungrounded} odrzuconych (bez pokrycia)"
        )
        return PhaseResult(
            ok=True, summary=summary, produced=produced, needs_human=True
        )
