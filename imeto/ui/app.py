"""GUI Gradio — cienka skórka realizująca próg człowieka (§ krok 10): wgraj
dokument → ekstrakcja → zaznacz, które fakty zaakceptować. Logika w rdzeniu;
tu tylko wołanie rdzenia i widżety.

Logika (extract_candidates / apply_decisions) jest oddzielona od warstwy Gradio,
żeby dała się testować bez uruchamiania interfejsu. `import gradio` siedzi wewnątrz
build_ui, więc rdzeń i testy nie ciągną tej ciężkiej zależności."""

from pathlib import Path
from typing import Any

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore
from imeto.phases.base import PhaseContext
from imeto.phases.extract import ExtractPhase


def extract_candidates(
    store: ProvenanceStore, document: str, llm: LLMClient
) -> list[tuple[int, str]]:
    """Uruchamia ekstrakcję i zwraca listę (id_dowodu, etykieta) kandydatów."""
    result = ExtractPhase(Path(document)).run(PhaseContext(store=store, llm=llm))
    out: list[tuple[int, str]] = []
    for eid in result.produced:
        ev = store.get_evidence(eid)
        out.append((eid, f"{ev.statement} — „{ev.quote}”"))
    return out


def apply_decisions(
    store: ProvenanceStore,
    all_ids: list[int],
    accepted_ids: list[int],
    by: str = "operator",
) -> tuple[int, int]:
    """Akceptuje zaznaczone, odrzuca resztę. Zwraca (zaakceptowane, odrzucone)."""
    accepted = set(accepted_ids)
    for eid in all_ids:
        if eid in accepted:
            store.accept_evidence(eid, by=by)
        else:
            store.reject_evidence(eid, by=by)
    return len(accepted), len(all_ids) - len(accepted)


def build_ui() -> Any:
    import gradio as gr

    store = ProvenanceStore(settings.db_url)

    def on_extract(document: str | None, base_url: str, model: str):  # type: ignore[no-untyped-def]
        if not document:
            return gr.update(choices=[], value=[]), [], "Wgraj dokument."
        if not model:
            return gr.update(choices=[], value=[]), [], "Podaj nazwę modelu."
        llm = LLMClient(
            base_url=base_url,
            api_key=settings.llm_api_key,
            model=model,
            temperature=settings.llm_temperature,
            json_mode=settings.llm_json_mode,
        )
        cands = extract_candidates(store, document, llm)
        choices = [(label, eid) for eid, label in cands]
        ids = [eid for eid, _ in cands]
        msg = f"Wydobyto {len(ids)} kandydatów."
        return gr.update(choices=choices, value=ids), ids, msg

    def on_decide(selected: list[int], all_ids: list[int]):  # type: ignore[no-untyped-def]
        acc, rej = apply_decisions(store, all_ids, selected)
        return f"Zaakceptowano {acc}, odrzucono {rej}."

    with gr.Blocks(title="IMeTo") as ui:
        gr.Markdown("# IMeTo — ekstrakcja faktów z pokryciem w źródle")
        with gr.Row():
            base_url = gr.Textbox(label="Adres modelu", value=settings.llm_base_url)
            model = gr.Textbox(label="Model", value=settings.llm_model)
        document = gr.File(label="Dokument (PDF/DOCX)", type="filepath")
        extract_btn = gr.Button("Wydobądź fakty", variant="primary")
        candidates = gr.CheckboxGroup(label="Kandydaci (zaznacz)", choices=[])
        decide_btn = gr.Button("Zatwierdź zaznaczone / odrzuć resztę")
        status = gr.Markdown()
        all_ids = gr.State([])

        extract_btn.click(
            on_extract, [document, base_url, model], [candidates, all_ids, status]
        )
        decide_btn.click(on_decide, [candidates, all_ids], [status])
    return ui


def launch() -> None:
    build_ui().launch()


if __name__ == "__main__":
    launch()
