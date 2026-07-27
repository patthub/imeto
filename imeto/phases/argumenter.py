"""Argumenter phase: verified facts → rubric assessment (FOR/AGAINST/GAPS).

Anti-hallucination discipline one level above extraction: an argument is model
reasoning, so it cannot be verified verbatim. Instead we require every FOR/AGAINST
argument to **rest on the given facts** (`based_on`), which are already verified and
accepted. An argument with no grounding fact (other than a GAP) is rejected. The human
judges the inferential leap itself (the gate)."""

from dataclasses import dataclass, field

from imeto.core.provenance import Claim
from imeto.core.schemas import Argumentation
from imeto.phases.base import PhaseContext, PhaseResult

ARGUE_SYSTEM = (
    "You assess the body of work according to the RUBRIC (below). You are given "
    "numbered FACTS (already verified). A fact marked ✓CONFIRMED has external evidence "
    "of impact (a quote from an independent source) — its impact is DOCUMENTED, not "
    "merely declared; that is a stronger basis for a FOR argument. Relate the facts to "
    "the rubric. Return only JSON:\n"
    '{"arguments": [{"side": "for|against|gap", "statement": "...", '
    '"based_on": [1, 3]}]}\n'
    "- side: for (facts support meeting the criterion) | against (they undermine it) | "
    "gap (a significant gap, e.g. impact declared without evidence).\n"
    "- statement: the argument in your own words, concisely.\n"
    "- based_on: the numbers of the FACTS the argument rests on. For for/against give "
    "at least one. For gap it may be empty (it indicates a gap).\n"
    "- Rely EXCLUSIVELY on the given facts; do not add information beyond them."
)


def _facts_text(ctx: PhaseContext, claims: list[Claim]) -> str:
    """Numbered facts; a fact with external corroboration (dossier internal+external)
    gets a ✓CONFIRMED marker + quote — the argumenter weighs documented impact."""
    lines: list[str] = []
    for i, c in enumerate(claims, 1):
        ext = ctx.store.external_evidence_for_claim(c.id) if c.id is not None else []
        mark = " ✓CONFIRMED" if ext else ""
        lines.append(f"[{i}]{mark} {c.statement}")
        for ev in ext:
            src = ctx.store.get_source(ev.source_id)
            lines.append(f"    ↳ „{ev.quote}” — {src.local_identifier}")
    return "\n".join(lines)


@dataclass
class ArgumenterPhase:
    source_id: int
    criterion: str = "kryterium_iii"
    claim_status: str | None = "accepted"  # we assess accepted facts
    name: str = field(default="argue")

    def run(self, ctx: PhaseContext) -> PhaseResult:
        claims = ctx.store.claims_for_source(self.source_id, status=self.claim_status)
        if not claims:
            return PhaseResult(
                ok=False,
                summary=f"source {self.source_id}: no facts to assess "
                f"(status={self.claim_status})",
            )

        rubric = ctx.skills.load(self.criterion, subdir="criteria")
        system = f"{ARGUE_SYSTEM}\n\n## Rubric\n{rubric}"
        facts_text = _facts_text(ctx, claims)
        result = ctx.llm.structured(system, facts_text, Argumentation)

        idx_to_id: dict[int, int] = {}
        for i, c in enumerate(claims, 1):
            if c.id is not None:
                idx_to_id[i] = c.id
        activity = f"argue:{self.source_id}"
        agent = ctx.llm.model
        produced: list[int] = []
        ungrounded = 0
        counts = {"for": 0, "against": 0, "gap": 0}

        for arg in result.arguments:
            claim_ids = [idx_to_id[i] for i in arg.based_on if i in idx_to_id]
            if arg.side in ("for", "against") and not claim_ids:
                ungrounded += 1  # reasoning with no grounding in facts — reject
                continue
            aid = ctx.store.add_argument(
                self.source_id,
                self.criterion,
                arg.side,
                arg.statement,
                claim_ids,
                activity=activity,
                agent=agent,
            )
            produced.append(aid)
            counts[arg.side] += 1

        summary = (
            f"source {self.source_id} / {self.criterion}: "
            f"{counts['for']} FOR, {counts['against']} AGAINST, {counts['gap']} GAPS "
            f"({ungrounded} rejected without grounding)"
        )
        return PhaseResult(
            ok=True, summary=summary, produced=produced, needs_human=True
        )
