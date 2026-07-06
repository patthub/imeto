"""CLI (Typer). Cienka skórka: wiąże konfigurację z rdzeniem i uruchamia fazy.
Logika nigdy tutaj — CLI tylko woła rdzeń (zasada nadrzędna z §2)."""

from pathlib import Path

import typer

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore
from imeto.ingest.loaders import fetch_by_doi, fetch_works_by_orcid
from imeto.ingest.sources import source_from_fetched, source_from_file
from imeto.phases.base import PhaseContext
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
    result = ExtractPhase(source_id, work_type).run(ctx)
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
    work_type: WorkType | None = typer.Option(
        None, "--type", "-t", help="Typ wytworu (wymagany dla --doi jeśli nieznany)"
    ),
) -> None:
    """Pobierz wytwór z API i wydobądź fakty (--doi), albo wypisz prace (--orcid)."""
    if orcid:
        dois = fetch_works_by_orcid(orcid)
        typer.echo(f"Prace ORCID {orcid} ({len(dois)}):")
        for d in dois:
            typer.echo(f"  {d}")
        typer.echo("Uruchom ekstrakcję: imeto ingest --doi <DOI> --type <typ>")
        return
    if not doi:
        raise typer.BadParameter("podaj --doi albo --orcid")

    fetched = fetch_by_doi(doi, contact_email=settings.contact_email)
    wt = work_type or fetched.work_type
    if wt is None:
        raise typer.BadParameter("nie rozpoznano typu wytworu — podaj --type")
    if not fetched.full_text:
        typer.echo("Uwaga: brak abstraktu z API — nie ma z czego wydobywać faktów.")
    store, ctx = _context()
    source_id, created = source_from_fetched(store, fetched)
    _extract_or_reuse(store, ctx, source_id, created, wt)


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
def ui() -> None:
    """Uruchom interfejs Gradio (próg człowieka: akceptuj/odrzuć kandydatów)."""
    from imeto.ui.app import launch  # lazy: Gradio ciągniemy tylko przy uruchomieniu UI

    launch()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
