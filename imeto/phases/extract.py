"""Extraction phase: source (already in the store) → facts (direct/inferred) with
verbatim-anchored grounds.

The phase operates on a `source_id` — acquiring the source (from a file or an API)
belongs to the ingest layer (`imeto.ingest.sources`). This way extraction from a file
and from an API runs on the same code.

It enforces the agreed rule:
- every ground (quote) is verified verbatim via `add_evidence`,
- a fact with not a single verified ground = hallucination → REJECTED,
- a fact with >=1 ground is stored as a `Claim` with its `kind` preserved
  (direct/inferred); missing grounds are counted (a "partial" fact),
- the fact kind (direct vs inferred) is never conflated."""

from collections.abc import Callable
from dataclasses import dataclass, field

from imeto.core.chunking import chunk_text
from imeto.core.provenance import SpanNotVerified
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.core.span import _fold
from imeto.phases.base import PhaseContext, PhaseResult
from imeto.worktypes import WorkType


def _dedup_facts(facts: list[ExtractedFact]) -> list[ExtractedFact]:
    """Drops facts with an identical set of quotes (duplicates from overlapping
    chunks). Facts with differing quotes are kept."""
    seen: set[frozenset[str]] = set()
    out: list[ExtractedFact] = []
    for fact in facts:
        key = frozenset(_fold(q).strip().lower() for q in fact.quotes)
        if key not in seen:
            seen.add(key)
            out.append(fact)
    return out


EXTRACT_SYSTEM = (
    "You are an assistant that extracts facts from scholarly works. Return only JSON:\n"
    '{"facts": [{"statement": "...", "kind": "direct|inferred", '
    '"quotes": ["...", "..."]}]}\n'
    "- statement: the fact in your own words, concisely.\n"
    '- kind: "direct" when the fact is stated explicitly in the text; '
    '"inferred" when you inferred it from the text.\n'
    "- quotes: verbatim fragments of the SOURCE (copied character for character) that "
    'the fact rests on. For "direct" they are the support; for "inferred" they are the '
    "PREMISES.\n"
    "- Every fact MUST have at least one quote. Do not invent quotes: "
    "if a fragment is not in the text, do not use it.\n"
    '- If you find no facts, return {"facts": []}.'
)


@dataclass
class ExtractPhase:
    source_id: int
    work_type: WorkType
    name: str = field(default="extract")
    chunk_chars: int = 6000  # threshold for splitting long text (model context)
    # optional preview/interrupt for the UI: per-chunk progress, cooperative stop
    # (checked BETWEEN chunks — a model call is not interruptible mid-flight)
    on_progress: Callable[[str], None] | None = None
    should_stop: Callable[[], bool] | None = None

    def run(self, ctx: PhaseContext) -> PhaseResult:
        src = ctx.store.get_source(self.source_id)
        # base (universal invariants) + work-type skill (what counts as a fact)
        skill = ctx.skills.load(self.work_type.value)
        system = f"{EXTRACT_SYSTEM}\n\n{skill}"
        # long text (e.g. a full OA article) is split into overlapping chunks;
        # quotes are then verified against the WHOLE full_text (global offsets)
        chunks = chunk_text(src.full_text, self.chunk_chars)
        # ponytail: cost = 1 model call per chunk; for very long texts add a
        #           limit/sampling once runs become expensive.
        raw: list[ExtractedFact] = []
        failed_chunks = 0
        stopped = False
        for i, chunk in enumerate(chunks, 1):
            if self.should_stop is not None and self.should_stop():
                stopped = True
                break
            # a chunk counter makes sense only when the text is split; with 1 chunk
            # only the clock remains (a single model generation has no partial progress)
            if self.on_progress is not None and len(chunks) > 1:
                self.on_progress(f"chunk {i}/{len(chunks)}")
            try:
                raw.extend(ctx.llm.structured(system, chunk, Extraction).facts)
            except Exception:
                # ponytail: a single chunk (a network/model blip) must not kill the
                #           whole extraction — count it and move on.
                failed_chunks += 1
        facts = _dedup_facts(raw)

        activity = f"extract:{self.source_id}"
        agent = ctx.llm.model
        produced: list[int] = []
        ungrounded = 0  # facts with no verified ground at all (rejected)
        partial = 0  # facts with some grounds unverified

        for fact in facts:
            ev_ids: list[int] = []
            failed = 0
            for quote in fact.quotes:
                try:
                    ev_ids.append(
                        ctx.store.add_evidence(
                            self.source_id, quote, activity=activity, agent=agent
                        )
                    )
                except SpanNotVerified:
                    failed += 1
            if not ev_ids:
                ungrounded += 1  # no coverage at all — hallucination, skip it
                continue
            if failed:
                partial += 1
            claim_id = ctx.store.add_claim(
                self.source_id,
                fact.statement,
                fact.kind,
                ev_ids,
                activity=activity,
                agent=agent,
            )
            produced.append(claim_id)

        frag = f", {len(chunks)} chunks" if len(chunks) > 1 else ""
        frag += f" ({failed_chunks} failed)" if failed_chunks else ""
        stop = " [STOPPED by user]" if stopped else ""
        summary = (
            f"source {self.source_id}: {len(produced)} facts saved "
            f"({partial} partial), {ungrounded} rejected (no grounding)"
            f"{frag}{stop}"
        )
        return PhaseResult(
            ok=True, summary=summary, produced=produced, needs_human=True
        )
