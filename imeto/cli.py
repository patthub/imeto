"""CLI (Typer). Cienka skórka: wiąże konfigurację z rdzeniem i uruchamia fazy.
Logika nigdy tutaj — CLI tylko woła rdzeń (zasada nadrzędna z §2)."""

from pathlib import Path

import typer

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore
from imeto.ingest.loaders import fetch_by_doi, fetch_works_by_orcid
from imeto.ingest.sources import source_from_fetched, source_from_file
from imeto.phases.base import PhaseContext, PhaseResult
from imeto.phases.extract import ExtractPhase
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType

app = typer.Typer(help="IMeTo — ekstrakcja faktów z pokryciem w źródle.")


@app.callback()
def _cb() -> None:
    """Wymusza nazwane podkomendy (imeto run ...)."""


def _context() -> tuple[ProvenanceStore, PhaseContext]:
    store = ProvenanceStore(settings.db_url)
    llm = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        json_mode=settings.llm_json_mode,
    )
    ctx = PhaseContext(
        store=store, llm=llm, skills=SkillRegistry(settings.knowledge_dir)
    )
    return store, ctx


def _print(store: ProvenanceStore, result: PhaseResult) -> None:
    typer.echo(result.summary)
    for cid in result.produced:
        claim = store.get_claim(cid)
        typer.echo(f"  [{cid}] ({claim.kind}) {claim.statement}")
        for ev in store.evidence_for_claim(cid):
            typer.echo(f'      „{ev.quote}” ({ev.start}–{ev.end})')


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
    source_id = source_from_file(store, document, work_type)
    _print(store, ExtractPhase(source_id, work_type).run(ctx))


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
    source_id = source_from_fetched(store, fetched)
    _print(store, ExtractPhase(source_id, wt).run(ctx))


@app.command()
def ui() -> None:
    """Uruchom interfejs Gradio (próg człowieka: akceptuj/odrzuć kandydatów)."""
    from imeto.ui.app import launch  # lazy: Gradio ciągniemy tylko przy uruchomieniu UI

    launch()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
