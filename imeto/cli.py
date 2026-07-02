"""CLI (Typer). Cienka skórka: wiąże konfigurację z rdzeniem i uruchamia fazy.
Logika nigdy tutaj — CLI tylko woła rdzeń (zasada nadrzędna z §2)."""

from pathlib import Path

import typer

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore
from imeto.phases.base import PhaseContext
from imeto.phases.extract import ExtractPhase
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType

app = typer.Typer(help="IMeTo — ekstrakcja faktów z pokryciem w źródle.")


@app.callback()
def _cb() -> None:
    """Wymusza nazwane podkomendy (imeto run ...)."""


@app.command()
def run(
    document: Path = typer.Argument(
        ..., exists=True, dir_okay=False, help="PDF lub DOCX do przetworzenia"
    ),
    work_type: WorkType = typer.Option(
        ..., "--type", "-t", help="Typ wytworu: article | report | proposal"
    ),
) -> None:
    """Wydobądź fakty z DOKUMENTU (danego TYPU) i zapisz je do provenance."""
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
    result = ExtractPhase(document, work_type).run(ctx)

    typer.echo(result.summary)
    for cid in result.produced:
        claim = store.get_claim(cid)
        typer.echo(f"  [{cid}] ({claim.kind}) {claim.statement}")
        for ev in store.evidence_for_claim(cid):
            typer.echo(f'      „{ev.quote}” ({ev.start}–{ev.end})')


@app.command()
def ui() -> None:
    """Uruchom interfejs Gradio (próg człowieka: akceptuj/odrzuć kandydatów)."""
    from imeto.ui.app import launch  # lazy: Gradio ciągniemy tylko przy uruchomieniu UI

    launch()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
