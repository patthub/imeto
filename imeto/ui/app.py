"""GUI Gradio — cienka skórka: wgraj/pobierz źródło → fakty → zatwierdź →
oceń wg Kryterium III (ZA/PRZECIW/LUKI). Logika w rdzeniu; tu tylko wołanie i widżety.

Logika (extract_* / apply_* / argue_*) jest oddzielona od Gradio, testowalna bez UI.
`import gradio` siedzi wewnątrz build_ui."""

from dataclasses import replace
from typing import Any

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore
from imeto.ingest.loaders import fetch_by_doi, fetch_oa_fulltext
from imeto.ingest.sources import (
    source_from_fetched,
    source_from_file,
    source_from_url,
)
from imeto.phases.argumenter import ArgumenterPhase
from imeto.phases.base import PhaseContext
from imeto.phases.corroborate import corroborate_one
from imeto.phases.extract import ExtractPhase
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType

Candidates = list[tuple[int, str]]


def _run_phase(
    store: ProvenanceStore,
    skills: SkillRegistry,
    source_id: int,
    work_type: WorkType,
    llm: LLMClient,
) -> Candidates:
    ctx = PhaseContext(store=store, llm=llm, skills=skills)
    phase = ExtractPhase(source_id, work_type, chunk_chars=settings.chunk_chars)
    result = phase.run(ctx)
    out: Candidates = []
    for cid in result.produced:
        claim = store.get_claim(cid)
        grounds = " | ".join(f"„{ev.quote}”" for ev in store.evidence_for_claim(cid))
        out.append((cid, f"({claim.kind}) {claim.statement} — {grounds}"))
    return out


def extract_candidates(
    store: ProvenanceStore,
    skills: SkillRegistry,
    document: str,
    work_type: WorkType,
    llm: LLMClient,
) -> tuple[int, Candidates]:
    source_id, _ = source_from_file(store, document, work_type)
    return source_id, _run_phase(store, skills, source_id, work_type, llm)


def extract_candidates_from_doi(
    store: ProvenanceStore,
    skills: SkillRegistry,
    doi: str,
    work_type: WorkType,
    llm: LLMClient,
    full_text: bool = False,
) -> tuple[int, Candidates]:
    fetched = fetch_by_doi(doi, contact_email=settings.contact_email)
    if full_text and fetched.oa_pdf_url:
        text = fetch_oa_fulltext(fetched.oa_pdf_url)
        if text:
            fetched = replace(fetched, full_text=text)
    source_id, _ = source_from_fetched(store, fetched)
    return source_id, _run_phase(store, skills, source_id, work_type, llm)


def extract_candidates_from_url(
    store: ProvenanceStore,
    skills: SkillRegistry,
    url: str,
    work_type: WorkType,
    llm: LLMClient,
) -> tuple[int, Candidates]:
    source_id, _ = source_from_url(store, url, work_type)
    return source_id, _run_phase(store, skills, source_id, work_type, llm)


def apply_decisions(
    store: ProvenanceStore,
    all_ids: list[int],
    accepted_ids: list[int],
    by: str = "operator",
) -> tuple[int, int]:
    """Akceptuje zaznaczone fakty, odrzuca resztę."""
    accepted = set(accepted_ids)
    for cid in all_ids:
        if cid in accepted:
            store.accept_claim(cid, by=by)
        else:
            store.reject_claim(cid, by=by)
    return len(accepted), len(all_ids) - len(accepted)


def argue_candidates(
    store: ProvenanceStore,
    skills: SkillRegistry,
    source_id: int,
    llm: LLMClient,
    criterion: str = "kryterium_iii",
) -> Candidates:
    """Buduje argumenty ZA/PRZECIW/LUKI nad ZAAKCEPTOWANYMI faktami źródła."""
    ctx = PhaseContext(store=store, llm=llm, skills=skills)
    result = ArgumenterPhase(source_id, criterion).run(ctx)
    out: Candidates = []
    for aid in result.produced:
        arg = store.get_argument(aid)
        facts = " | ".join(c.statement for c in store.claims_for_argument(aid))
        tail = f"  ← {facts}" if facts else ""
        out.append((aid, f"[{arg.side.upper()}] {arg.statement}{tail}"))
    return out


def apply_argument_decisions(
    store: ProvenanceStore,
    all_ids: list[int],
    accepted_ids: list[int],
    by: str = "ekspert",
) -> tuple[int, int]:
    accepted = set(accepted_ids)
    for aid in all_ids:
        if aid in accepted:
            store.accept_argument(aid, by=by)
        else:
            store.reject_argument(aid, by=by)
    return len(accepted), len(all_ids) - len(accepted)


def build_ui() -> Any:
    import gradio as gr

    store = ProvenanceStore(settings.db_url)
    skills = SkillRegistry(settings.knowledge_dir)

    def _llm(base_url: str, model: str) -> LLMClient:
        return LLMClient(
            base_url=base_url,
            api_key=settings.llm_api_key,
            model=model,
            temperature=settings.llm_temperature,
            json_mode=settings.llm_json_mode,
        )

    def on_extract(  # type: ignore[no-untyped-def]
        mode, document, doi, url, full_text, work_type, base_url, model
    ):
        empty = gr.update(choices=[], value=[], visible=False)
        if not model:
            return empty, [], None, "Podaj nazwę modelu."
        wt = WorkType(work_type)
        try:
            llm = _llm(base_url, model)
            if mode == "DOI":
                if not doi.strip():
                    return empty, [], None, "Podaj DOI."
                sid, cands = extract_candidates_from_doi(
                    store, skills, doi.strip(), wt, llm, full_text
                )
            elif mode == "URL":
                if not url.strip():
                    return empty, [], None, "Podaj URL."
                sid, cands = extract_candidates_from_url(
                    store, skills, url.strip(), wt, llm
                )
            else:
                if not document:
                    return empty, [], None, "Wgraj dokument."
                sid, cands = extract_candidates(store, skills, document, wt, llm)
        except Exception as e:  # noqa: BLE001
            return empty, [], None, f"Błąd: {e}"
        choices = [(label, cid) for cid, label in cands]
        ids = [cid for cid, _ in cands]
        return (
            gr.update(choices=choices, value=ids, visible=True),
            ids, sid, f"Wydobyto {len(ids)}.",
        )

    def on_decide(selected, all_ids):  # type: ignore[no-untyped-def]
        acc, rej = apply_decisions(store, all_ids, selected)
        return f"Zaakceptowano {acc} faktów, odrzucono {rej}."

    def on_argue(source_id, base_url, model):  # type: ignore[no-untyped-def]
        empty = gr.update(choices=[], value=[], visible=False)
        if not source_id:
            return empty, [], "Najpierw wydobądź i zatwierdź fakty."
        try:
            llm = _llm(base_url, model)
            args = argue_candidates(store, skills, int(source_id), llm)
        except Exception as e:  # noqa: BLE001
            return empty, [], f"Błąd: {e}"
        if not args:
            return empty, [], "Brak argumentów (zatwierdź najpierw fakty)."
        choices = [(label, aid) for aid, label in args]
        ids = [aid for aid, _ in args]
        msg = f"Zbudowano {len(ids)} argumentów."
        return gr.update(choices=choices, value=ids, visible=True), ids, msg

    def on_decide_args(selected, all_ids):  # type: ignore[no-untyped-def]
        acc, rej = apply_argument_decisions(store, all_ids, selected)
        return f"Zaakceptowano {acc} argumentów, odrzucono {rej}."

    def on_corroborate(source_id, base_url, model):  # type: ignore[no-untyped-def]
        if not source_id:
            yield "Najpierw wydobądź i zatwierdź fakty."
            return
        claims = store.claims_for_source(int(source_id), status="accepted")
        if not claims:
            yield "Brak zatwierdzonych faktów — najpierw zatwierdź fakty w sekcji 1."
            return
        llm = _llm(base_url, model)
        activity = f"corroborate:{source_id}"
        lines: list[str] = []
        for i, claim in enumerate(claims, 1):
            prog = f"⏳ Sprawdzam {i}/{len(claims)}: {claim.statement[:70]}…"
            yield "\n".join([*lines, prog])
            try:
                eid = corroborate_one(
                    store, llm, claim, activity=activity, agent=llm.model
                )
            except Exception as e:  # noqa: BLE001
                yield "\n".join([*lines, f"⚠️ błąd przy fakcie {i}: {e}"])
                continue
            if eid is not None:
                ev = store.get_evidence(eid)
                src = store.get_source(ev.source_id)
                lines.append(f"- ✅ **{claim.statement}**")
                lines.append(f"    „{ev.quote}” — {src.local_identifier}")
        yield "\n".join(lines) if lines else "Nie znaleziono potwierdzeń w sieci."

    with gr.Blocks(title="IMeTo") as ui:
        gr.Markdown("# IMeTo")
        gr.Markdown(
            "Fakty z pokryciem w źródle → potwierdzenia wpływu w sieci "
            "→ ocena wg Kryterium III"
        )

        with gr.Accordion("Ustawienia modelu", open=False):
            base_url = gr.Textbox(label="Adres modelu", value=settings.llm_base_url)
            model = gr.Textbox(label="Model", value=settings.llm_model)

        gr.Markdown("## Źródło")
        mode = gr.Radio(choices=["Plik", "DOI", "URL"], value="Plik", label="Tryb")
        document = gr.File(label="Dokument (PDF/DOCX)", type="filepath")
        work_type = gr.Dropdown(
            label="Typ wytworu",
            choices=[wt.value for wt in WorkType],
            value=WorkType.report.value,
        )
        doi = gr.Textbox(label="DOI", placeholder="10.1234/...")
        url = gr.Textbox(label="URL", placeholder="https://...")
        full_text = gr.Checkbox(label="Pełny tekst OA", value=False)

        gr.Markdown("## Krok 1 · Fakty")
        extract_btn = gr.Button("Wydobądź fakty", variant="primary")
        candidates = gr.CheckboxGroup(
            label="Zaznacz do przyjęcia", choices=[], visible=False
        )
        decide_btn = gr.Button("Zatwierdź zaznaczone fakty")
        status = gr.Markdown()

        gr.Markdown("## Krok 2 · Potwierdzenia wpływu w sieci")
        corroborate_btn = gr.Button("Potwierdź fakty w sieci")
        corr_output = gr.Markdown()

        gr.Markdown("## Krok 3 · Ocena wg Kryterium III")
        argue_btn = gr.Button("Oceń wg Kryterium III", variant="primary")
        arguments = gr.CheckboxGroup(
            label="Zaznacz do przyjęcia", choices=[], visible=False
        )
        decide_args_btn = gr.Button("Zatwierdź zaznaczone argumenty")
        arg_status = gr.Markdown()

        stop_btn = gr.Button("Zatrzymaj")

        source_id = gr.State(None)
        all_ids = gr.State([])
        arg_ids = gr.State([])

        ev_extract = extract_btn.click(
            on_extract,
            [mode, document, doi, url, full_text, work_type, base_url, model],
            [candidates, all_ids, source_id, status],
        )
        decide_btn.click(on_decide, [candidates, all_ids], [status])
        ev_argue = argue_btn.click(
            on_argue, [source_id, base_url, model], [arguments, arg_ids, arg_status]
        )
        decide_args_btn.click(on_decide_args, [arguments, arg_ids], [arg_status])
        ev_corr = corroborate_btn.click(
            on_corroborate, [source_id, base_url, model], [corr_output]
        )
        stop_btn.click(None, None, None, cancels=[ev_extract, ev_argue, ev_corr])
    return ui


def launch() -> None:
    build_ui().queue().launch()


if __name__ == "__main__":
    launch()
