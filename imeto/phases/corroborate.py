"""Faza korroboracji: dla każdego faktu z dokumentu szukaj w internecie POTWIERDZENIA
jego społecznego wpływu i zakotwicz je dosłownie.

Napędzane faktami i automatyczne: fakt → zapytanie → wyszukiwanie → pobranie kandydatów
→ LLM ocenia, czy strona potwierdza wpływ i podaje DOSŁOWNY cytat → cytat weryfikowany
znak w znak na tej stronie (add_evidence) → dowód zewnętrzny wpięty do faktu.

Dyscyplina anty-halucynacyjna: potwierdzenie MUSI być dosłownym fragmentem realnie
pobranej strony — LLM nie może go zmyślić. Wyszukiwarka i strony zwracają KANDYDATÓW;
człowiek ocenia, które potwierdzenia liczą (Z1)."""

from dataclasses import dataclass, field

from imeto.core.provenance import Claim, SpanNotVerified
from imeto.core.schemas import Corroboration
from imeto.ingest.sources import source_from_text
from imeto.ingest.web import fetch_url_text
from imeto.phases.base import PhaseContext, PhaseResult
from imeto.tools.web_search import web_search

CORROBORATE_SYSTEM = (
    "Sprawdzasz, czy STRONA potwierdza SPOŁECZNY WPŁYW opisanego FAKTU — realny skutek "
    "poza nauką: wdrożenie, przyjęcie przez instytucję, cytowanie w polityce, "
    "zmiana praktyki. Zwróć tylko JSON:\n"
    '{"confirms": true/false, "quote": "..."}\n'
    "- confirms: true TYLKO gdy strona faktycznie potwierdza wpływ TEGO faktu.\n"
    "- quote: DOSŁOWNY fragment STRONY potwierdzający wpływ (skopiowany znak w znak); "
    "pusty, gdy confirms=false.\n"
    "- Nie zmyślaj cytatu. Sama wzmianka o temacie bez potwierdzenia wpływu to false."
)


@dataclass
class CorroboratePhase:
    source_id: int
    claim_status: str | None = "accepted"
    max_candidates: int = 3
    page_chars: int = 6000
    name: str = field(default="corroborate")

    def run(self, ctx: PhaseContext) -> PhaseResult:
        claims = ctx.store.claims_for_source(self.source_id, status=self.claim_status)
        if not claims:
            return PhaseResult(
                ok=False,
                summary=f"źródło {self.source_id}: brak faktów "
                f"(status={self.claim_status})",
            )
        activity = f"corroborate:{self.source_id}"
        agent = ctx.llm.model
        produced: list[int] = []  # id dowodów-potwierdzeń
        for claim in claims:
            eid = self._corroborate(ctx, claim, activity, agent)
            if eid is not None:
                produced.append(eid)
        summary = (
            f"źródło {self.source_id}: potwierdzono {len(produced)}/{len(claims)} "
            "faktów w sieci"
        )
        return PhaseResult(
            ok=True, summary=summary, produced=produced, needs_human=True
        )

    def _corroborate(
        self, ctx: PhaseContext, claim: Claim, activity: str, agent: str
    ) -> int | None:
        assert claim.id is not None
        for cand in web_search(claim.statement, max_results=self.max_candidates):
            text = fetch_url_text(cand.url)
            if not text:
                continue
            user = (
                f"FAKT: {claim.statement}\n\n"
                f"STRONA ({cand.url}):\n{text[: self.page_chars]}"
            )
            verdict = ctx.llm.structured(CORROBORATE_SYSTEM, user, Corroboration)
            if not verdict.confirms or not verdict.quote.strip():
                continue
            ext_sid, _ = source_from_text(ctx.store, cand.url, text)
            try:
                ev = ctx.store.add_evidence(
                    ext_sid, verdict.quote, activity=activity, agent=agent
                )
            except SpanNotVerified:
                continue  # LLM zmyślił cytat — odrzuć, próbuj kolejnego kandydata
            ctx.store.link_evidence(claim.id, ev)
            return ev
        return None
