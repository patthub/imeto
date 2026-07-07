"""Faza argumentera: zweryfikowane fakty → ocena wg rubryki (ZA/PRZECIW/LUKI).

Dyscyplina anty-halucynacyjna o poziom wyżej niż ekstrakcja: argument to rozumowanie
modelu, więc nie da się go zweryfikować dosłownie. Zamiast tego wymagamy, by każdy
argument ZA/PRZECIW **opierał się na podanych faktach** (`based_on`), które są już
zweryfikowane i zaakceptowane. Argument bez faktu-gruntu (poza LUKĄ) jest odrzucany.
Człowiek ocenia sam skok wnioskowy (próg)."""

from dataclasses import dataclass, field

from imeto.core.schemas import Argumentation
from imeto.phases.base import PhaseContext, PhaseResult

ARGUE_SYSTEM = (
    "Oceniasz dorobek według RUBRYKI (poniżej). Dostajesz ponumerowane FAKTY "
    "(już zweryfikowane). Odnieś fakty do rubryki. Zwróć tylko JSON:\n"
    '{"arguments": [{"side": "za|przeciw|luka", "statement": "...", '
    '"based_on": [1, 3]}]}\n'
    "- side: za (fakty wspierają spełnienie kryterium) | przeciw (podważają) | "
    "luka (istotny brak).\n"
    "- statement: argument własnymi słowami, zwięźle.\n"
    "- based_on: numery FAKTÓW, na których argument się opiera. Dla za/przeciw podaj "
    "co najmniej jeden. Dla luka może być pusty (to wskazanie braku).\n"
    "- Opieraj się WYŁĄCZNIE na podanych faktach; nie dodawaj informacji spoza nich."
)


@dataclass
class ArgumenterPhase:
    source_id: int
    criterion: str = "kryterium_iii"
    claim_status: str | None = "accepted"  # oceniamy fakty zaakceptowane
    name: str = field(default="argue")

    def run(self, ctx: PhaseContext) -> PhaseResult:
        claims = ctx.store.claims_for_source(self.source_id, status=self.claim_status)
        if not claims:
            return PhaseResult(
                ok=False,
                summary=f"źródło {self.source_id}: brak faktów do oceny "
                f"(status={self.claim_status})",
            )

        rubric = ctx.skills.load(self.criterion, subdir="criteria")
        system = f"{ARGUE_SYSTEM}\n\n## Rubryka\n{rubric}"
        facts_text = "\n".join(f"[{i}] {c.statement}" for i, c in enumerate(claims, 1))
        result = ctx.llm.structured(system, facts_text, Argumentation)

        idx_to_id: dict[int, int] = {}
        for i, c in enumerate(claims, 1):
            if c.id is not None:
                idx_to_id[i] = c.id
        activity = f"argue:{self.source_id}"
        agent = ctx.llm.model
        produced: list[int] = []
        ungrounded = 0
        counts = {"za": 0, "przeciw": 0, "luka": 0}

        for arg in result.arguments:
            claim_ids = [idx_to_id[i] for i in arg.based_on if i in idx_to_id]
            if arg.side in ("za", "przeciw") and not claim_ids:
                ungrounded += 1  # rozumowanie bez oparcia w faktach — odrzucamy
                continue
            aid = ctx.store.add_argument(
                self.source_id, self.criterion, arg.side, arg.statement, claim_ids,
                activity=activity, agent=agent,
            )
            produced.append(aid)
            counts[arg.side] += 1

        summary = (
            f"źródło {self.source_id} / {self.criterion}: "
            f"{counts['za']} ZA, {counts['przeciw']} PRZECIW, {counts['luka']} LUKI "
            f"({ungrounded} odrzuconych bez oparcia)"
        )
        return PhaseResult(
            ok=True, summary=summary, produced=produced, needs_human=True
        )
