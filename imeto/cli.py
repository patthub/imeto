"""CLI (Typer). Cienka skórka: wiąże konfigurację z rdzeniem i uruchamia fazy.
Logika nigdy tutaj — CLI tylko woła rdzeń (zasada nadrzędna z §2)."""

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

app = typer.Typer(help="IMeTo — ekstrakcja faktów z pokryciem w źródle.")


@app.callback()
def _cb() -> None:
    """Wymusza nazwane podkomendy (imeto run ...)."""


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
            typer.echo(f'      „{ev.quote}” ({ev.start}–{ev.end})')


def _extract_or_reuse(
    store: ProvenanceStore, ctx: PhaseContext, source_id: int, created: bool,
    work_type: WorkType,
) -> None:
    """Ekstrahuje z nowego źródła; dla już zaimportowanego pokazuje istniejące fakty."""
    if not created:
        existing = [c.id for c in store.claims_for_source(source_id) if c.id]
        typer.echo(f"źródło już zaimportowane (source_id={source_id}) — pomijam")
        _print_claims(store, existing)
        return
    phase = ExtractPhase(source_id, work_type, chunk_chars=settings.chunk_chars)
    result = phase.run(ctx)
    typer.echo(result.summary)
    _print_claims(store, result.produced)


@app.command()
def run(
    document: Path = typer.Argument(
        ..., exists=True, dir_okay=False, help="PDF lub DOCX do przetworzenia"
    ),
    work_type: WorkType = typer.Option(
        ..., "--type", "-t", help="Typ wytworu: article | report | proposal | ..."
    ),
) -> None:
    """Wydobądź fakty z pliku DOKUMENTU (danego TYPU) i zapisz je do provenance."""
    store, ctx = _context()
    source_id, created = source_from_file(store, document, work_type)
    _extract_or_reuse(store, ctx, source_id, created, work_type)


@app.command()
def ingest(
    doi: str | None = typer.Option(None, "--doi", help="Pobierz wytwór po DOI"),
    orcid: str | None = typer.Option(None, "--orcid", help="Wypisz prace ORCID"),
    url: str | None = typer.Option(None, "--url", help="Pobierz stronę WWW"),
    work_type: WorkType | None = typer.Option(
        None, "--type", "-t", help="Typ wytworu (wymagany dla --doi jeśli nieznany)"
    ),
    full_text: bool = typer.Option(
        False, "--full-text", "-f", help="Pobierz pełny tekst OA (PDF), jeśli dostępny"
    ),
) -> None:
    """Pobierz źródło (--doi / --url) i wydobądź fakty, albo wypisz prace (--orcid)."""
    from dataclasses import replace

    if orcid:
        dois = fetch_works_by_orcid(orcid)
        typer.echo(f"Prace ORCID {orcid} ({len(dois)}):")
        for d in dois:
            typer.echo(f"  {d}")
        typer.echo("Uruchom ekstrakcję: imeto ingest --doi <DOI> --type <typ>")
        return
    if url:
        if work_type is None:
            raise typer.BadParameter("podaj --type dla --url")
        store, ctx = _context()
        try:
            source_id, created = source_from_url(store, url, work_type)
        except ValueError as e:
            typer.echo(str(e))  # martwy/zablokowany link — czytelnie, bez traceback
            raise typer.Exit(1) from e
        _extract_or_reuse(store, ctx, source_id, created, work_type)
        return
    if not doi:
        raise typer.BadParameter("podaj --doi, --url albo --orcid")

    fetched = fetch_by_doi(doi, contact_email=settings.contact_email)
    if full_text and fetched.oa_pdf_url:
        text = fetch_oa_fulltext(fetched.oa_pdf_url)
        if text:
            fetched = replace(fetched, full_text=text)
            typer.echo(f"pobrano pełny tekst OA ({len(text)} znaków)")
        else:
            typer.echo("nie udało się pobrać pełnego tekstu OA — używam abstraktu")
    elif full_text:
        typer.echo("brak pełnego tekstu OA dla tego DOI — używam abstraktu")

    wt = work_type or fetched.work_type
    if wt is None:
        raise typer.BadParameter("nie rozpoznano typu wytworu — podaj --type")
    if not fetched.full_text:
        typer.echo("Uwaga: brak tekstu z API — nie ma z czego wydobywać faktów.")
    store, ctx = _context()
    source_id, created = source_from_fetched(store, fetched)
    _extract_or_reuse(store, ctx, source_id, created, wt)


@app.command()
def argue(
    source_id: int = typer.Argument(..., help="id źródła (z imeto run/ingest)"),
    criterion: str = typer.Option("kryterium_iii", "--criterion", "-c"),
    status: str = typer.Option(
        "accepted", "--status", help="fakty: accepted | candidate | all"
    ),
) -> None:
    """Zbuduj argumenty ZA/PRZECIW/LUKI wg rubryki dla faktów źródła."""
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
def corroborate(
    source_id: int = typer.Argument(..., help="id źródła (z imeto run/ingest)"),
    status: str = typer.Option("accepted", "--status", help="fakty: accepted | all"),
    limit: int = typer.Option(3, "--limit", "-n", help="Kandydatów na fakt"),
) -> None:
    """Szukaj w sieci potwierdzeń społecznego wpływu zaakceptowanych faktów źródła."""
    store, ctx = _context()
    claim_status = None if status == "all" else status
    result = CorroboratePhase(source_id, claim_status, max_candidates=limit).run(ctx)
    typer.echo(result.summary)
    for eid in result.produced:
        ev = store.get_evidence(eid)
        src = store.get_source(ev.source_id)
        typer.echo(f"  ✓ {src.local_identifier}")
        typer.echo(f'    „{ev.quote}”')


@app.command("eval")
def evaluate(
    golden_dir: str = typer.Option("tests/golden", "--golden", help="Katalog golden"),
    repeat: int = typer.Option(1, "--repeat", "-n", help="Powtórzeń na przypadek"),
) -> None:
    """Zmierz jakość ekstrakcji na golden secie (recall / precyzja / rodzaj).

    Model bywa niedeterministyczny nawet przy temp=0 — użyj --repeat N (np. 5),
    by uśrednić po N przebiegach i zobaczyć rozrzut."""
    from statistics import mean

    from imeto.obs.eval import load_golden, run_case

    cases = load_golden(golden_dir)
    if not cases:
        typer.echo(f"brak przypadków w {golden_dir}")
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
        f"{'RAZEM':24} recall={mean(all_r):.2f} prec={mean(all_p):.2f} "
        f"kind={mean(all_k):.2f}"
    )


@app.command()
def search(
    query: str = typer.Argument(..., help="Zapytanie — szukaj dowodów wpływu"),
    limit: int = typer.Option(8, "--limit", "-n", help="Liczba kandydatów"),
) -> None:
    """Wyszukaj w sieci kandydatów na dowody (człowiek decyduje, co jest dowodem)."""
    from imeto.tools.web_search import web_search

    for r in web_search(query, max_results=limit):
        typer.echo(f"• {r.title}")
        typer.echo(f"  {r.url}")
        if r.snippet:
            typer.echo(f"  {r.snippet[:160]}")


@app.command()
def ui() -> None:
    """Uruchom interfejs Gradio (próg człowieka: akceptuj/odrzuć kandydatów)."""
    from imeto.ui.app import launch  # lazy: Gradio ciągniemy tylko przy uruchomieniu UI

    launch()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
