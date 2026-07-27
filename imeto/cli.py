"""CLI (Typer). Thin skin: wires config to the core and runs phases.
Logic never lives here — the CLI only calls the core (top-level rule from §2)."""

from pathlib import Path

import typer

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore
from imeto.ingest.loaders import (
    fetch_by_doi,
    fetch_oa_fulltext,
    fetch_works_by_orcid,
)
from imeto.ingest.sources import (
    source_from_fetched,
    source_from_file,
    source_from_url,
)
from imeto.phases.argumenter import ArgumenterPhase
from imeto.phases.base import PhaseContext
from imeto.phases.corroborate import CorroboratePhase
from imeto.phases.extract import ExtractPhase
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType

app = typer.Typer(help="IMeTo — extract facts grounded in the source.")


@app.callback()
def _cb() -> None:
    """Forces named subcommands (imeto run ...)."""


def _llm() -> LLMClient:
    return LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        json_mode=settings.llm_json_mode,
    )


def _context() -> tuple[ProvenanceStore, PhaseContext]:
    store = ProvenanceStore(settings.db_url)
    ctx = PhaseContext(
        store=store, llm=_llm(), skills=SkillRegistry(settings.knowledge_dir)
    )
    return store, ctx


def _print_claims(store: ProvenanceStore, claim_ids: list[int]) -> None:
    for cid in claim_ids:
        claim = store.get_claim(cid)
        typer.echo(f"  [{cid}] ({claim.kind}) {claim.statement}")
        for ev in store.evidence_for_claim(cid):
            typer.echo(f"      „{ev.quote}” ({ev.start}–{ev.end})")


def _extract_or_reuse(
    store: ProvenanceStore,
    ctx: PhaseContext,
    source_id: int,
    created: bool,
    work_type: WorkType,
) -> None:
    """Extracts from a new source; for an already-imported one shows existing claims."""
    if not created:
        existing = [c.id for c in store.claims_for_source(source_id) if c.id]
        typer.echo(f"source already imported (source_id={source_id}) — skipping")
        _print_claims(store, existing)
        return
    phase = ExtractPhase(source_id, work_type, chunk_chars=settings.chunk_chars)
    result = phase.run(ctx)
    typer.echo(result.summary)
    _print_claims(store, result.produced)


@app.command()
def run(
    document: Path = typer.Argument(
        ..., exists=True, dir_okay=False, help="PDF or DOCX to process"
    ),
    work_type: WorkType = typer.Option(
        ..., "--type", "-t", help="Work type: article | report | proposal | ..."
    ),
) -> None:
    """Extract claims from the DOCUMENT file (of given TYPE) and save to provenance."""
    store, ctx = _context()
    source_id, created = source_from_file(store, document, work_type)
    _extract_or_reuse(store, ctx, source_id, created, work_type)


@app.command()
def ingest(
    doi: str | None = typer.Option(None, "--doi", help="Fetch a work by DOI"),
    orcid: str | None = typer.Option(None, "--orcid", help="List ORCID works"),
    url: str | None = typer.Option(None, "--url", help="Fetch a web page"),
    work_type: WorkType | None = typer.Option(
        None, "--type", "-t", help="Work type (required for --doi if unknown)"
    ),
    full_text: bool = typer.Option(
        False, "--full-text", "-f", help="Fetch OA full text (PDF), if available"
    ),
) -> None:
    """Fetch a source (--doi / --url) and extract claims, or list works (--orcid)."""
    from dataclasses import replace

    if orcid:
        dois = fetch_works_by_orcid(orcid)
        typer.echo(f"ORCID works {orcid} ({len(dois)}):")
        for d in dois:
            typer.echo(f"  {d}")
        typer.echo("Run extraction: imeto ingest --doi <DOI> --type <type>")
        return
    if url:
        if work_type is None:
            raise typer.BadParameter("provide --type for --url")
        store, ctx = _context()
        try:
            source_id, created = source_from_url(store, url, work_type)
        except ValueError as e:
            typer.echo(str(e))  # dead/blocked link — readable, no traceback
            raise typer.Exit(1) from e
        _extract_or_reuse(store, ctx, source_id, created, work_type)
        return
    if not doi:
        raise typer.BadParameter("provide --doi, --url or --orcid")

    fetched = fetch_by_doi(doi, contact_email=settings.contact_email)
    if full_text and fetched.oa_pdf_url:
        text = fetch_oa_fulltext(fetched.oa_pdf_url)
        if text:
            fetched = replace(fetched, full_text=text)
            typer.echo(f"fetched OA full text ({len(text)} characters)")
        else:
            typer.echo("could not fetch OA full text — using the abstract")
    elif full_text:
        typer.echo("no OA full text for this DOI — using the abstract")

    wt = work_type or fetched.work_type
    if wt is None:
        raise typer.BadParameter("work type not recognized — provide --type")
    if not fetched.full_text:
        typer.echo("Warning: no text from the API — nothing to extract facts from.")
    store, ctx = _context()
    source_id, created = source_from_fetched(store, fetched)
    _extract_or_reuse(store, ctx, source_id, created, wt)


@app.command()
def argue(
    source_id: int = typer.Argument(..., help="source id (from imeto run/ingest)"),
    criterion: str = typer.Option("kryterium_iii", "--criterion", "-c"),
    status: str = typer.Option(
        "accepted", "--status", help="facts: accepted | candidate | all"
    ),
) -> None:
    """Build FOR/AGAINST/GAPS arguments per the rubric for a source's claims."""
    store, ctx = _context()
    claim_status = None if status == "all" else status
    result = ArgumenterPhase(source_id, criterion, claim_status).run(ctx)
    typer.echo(result.summary)
    for aid in result.produced:
        arg = store.get_argument(aid)
        typer.echo(f"  [{aid}] {arg.side.upper()}: {arg.statement}")
        for claim in store.claims_for_argument(aid):
            typer.echo(f"      ← {claim.statement}")


@app.command()
def suggest(
    source_id: int = typer.Argument(..., help="source id (from imeto run/ingest)"),
    criterion: str = typer.Option("kryterium_iii", "--criterion", "-c"),
    status: str = typer.Option("accepted", "--status", help="facts: accepted | all"),
) -> None:
    """Suggest leads and SAVE them on the claims (trail + editable query)."""
    from imeto.phases.suggest import run_suggester

    store, ctx = _context()
    claim_status = None if status == "all" else status
    leads = run_suggester(
        store, ctx.llm, ctx.skills, source_id, criterion, claim_status
    )
    typer.echo(f"source {source_id}: {len(leads)} leads (saved)")
    for lead in leads:
        typer.echo(f"  • {lead.lead}")
        typer.echo(f"    fact: {lead.statement}")
        typer.echo(f"    query: {lead.query}")


@app.command()
def corroborate(
    source_id: int = typer.Argument(..., help="source id (from imeto run/ingest)"),
    status: str = typer.Option("accepted", "--status", help="facts: accepted | all"),
    limit: int = typer.Option(3, "--limit", "-n", help="Candidates per fact"),
    leads: bool = typer.Option(
        True, "--leads/--no-leads", help="Run suggester first (saves leads)"
    ),
) -> None:
    """Search the web for social-impact corroboration of a source's accepted claims."""
    from imeto.phases.suggest import run_suggester

    store, ctx = _context()
    claim_status = None if status == "all" else status
    if leads:
        run_suggester(
            store, ctx.llm, ctx.skills, source_id, "kryterium_iii", claim_status
        )
    result = CorroboratePhase(source_id, claim_status, max_candidates=limit).run(ctx)
    typer.echo(result.summary)
    for eid in result.produced:
        ev = store.get_evidence(eid)
        src = store.get_source(ev.source_id)
        typer.echo(f"  ✓ {src.local_identifier}")
        typer.echo(f"    „{ev.quote}”")


@app.command("eval")
def evaluate(
    golden_dir: str = typer.Option("tests/golden", "--golden", help="Golden directory"),
    repeat: int = typer.Option(1, "--repeat", "-n", help="Repeats per case"),
) -> None:
    """Measure extraction quality on the golden set (recall / precision / kind).

    The model can be non-deterministic even at temp=0 — use --repeat N (e.g. 5)
    to average over N runs and see the spread."""
    from statistics import mean

    from imeto.obs.eval import load_golden, run_case

    cases = load_golden(golden_dir)
    if not cases:
        typer.echo(f"no cases in {golden_dir}")
        raise typer.Exit(1)
    llm, skills = _llm(), SkillRegistry(settings.knowledge_dir)
    all_r, all_p, all_k = [], [], []
    for case in cases:
        runs = [run_case(case, llm, skills) for _ in range(repeat)]
        r = [m.recall for m in runs]
        p = [m.precision for m in runs]
        k = [m.kind_accuracy for m in runs]
        line = (
            f"{case['name']:24} recall={mean(r):.2f} prec={mean(p):.2f} "
            f"kind={mean(k):.2f}"
        )
        if repeat > 1:
            line += f"  [prec {min(p):.2f}–{max(p):.2f}, n={repeat}]"
        typer.echo(line)
        all_r.append(mean(r))
        all_p.append(mean(p))
        all_k.append(mean(k))
    typer.echo(
        f"{'TOTAL':24} recall={mean(all_r):.2f} prec={mean(all_p):.2f} "
        f"kind={mean(all_k):.2f}"
    )


@app.command()
def search(
    query: str = typer.Argument(..., help="Query — search for impact evidence"),
    limit: int = typer.Option(8, "--limit", "-n", help="Number of candidates"),
) -> None:
    """Search the web for evidence candidates (a human decides what is evidence)."""
    from imeto.tools.web_search import web_search

    for r in web_search(query, max_results=limit):
        typer.echo(f"• {r.title}")
        typer.echo(f"  {r.url}")
        if r.snippet:
            typer.echo(f"  {r.snippet[:160]}")


@app.command()
def ui() -> None:
    """Launch the Gradio interface (human gate: accept/reject candidates)."""
    from imeto.ui.app import launch  # lazy: pull in Gradio only when the UI starts

    launch()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
