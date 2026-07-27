"""Gradio GUI — thin skin: upload/fetch source → claims → approve →
score by Criterion III (FOR/AGAINST/GAPS). Logic in the core; here just calls
and widgets.

The logic (extract_* / apply_* / argue_*) is decoupled from Gradio, testable without UI.
`import gradio` sits inside build_ui."""

import csv
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Literal

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import Evidence, ProvenanceStore
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
from imeto.phases.suggest import run_suggester, study_context
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType

Candidates = list[tuple[int, str]]

# claims table: all visible with provenance and context, nothing vanishes silently
FACTS_HEADERS = [
    "No.",
    "Kind",
    "Fact",
    "Quote in source",
    "Position",
    "Context",
    "Lead / query",
    "Impact (web)",
]

# markdown in text columns → cells render like prose (wrapping, links), not a
# cramped grid; narrow columns (Nr/Rodzaj/Pozycja) stay plain text
_DType = Literal["str", "markdown"]
FACTS_DATATYPES: list[_DType] = [
    "str",
    "str",
    "markdown",
    "markdown",
    "str",
    "markdown",
    "markdown",
    "markdown",
]
FACTS_WIDTHS: list[str | int] = ["4%", "9%", "20%", "19%", "7%", "19%", "12%", "10%"]

_TRAIL_MARK = {
    "candidate": "🔍",
    "internal": "internal (hint)",
    "unknown": "—",
}


def _context_window(text: str, start: int, end: int, pad: int = 120) -> str:
    """Text window around the quote — claim seen in sentence context, not alone."""
    a, b = max(0, start - pad), min(len(text), end + pad)
    snip = " ".join(text[a:b].split())
    return ("…" if a > 0 else "") + snip + ("…" if b < len(text) else "")


def _impact_cell(store: ProvenanceStore, ev: Evidence) -> str:
    """ "Impact" cell: quote + source as a clickable link when it's a URL."""
    ident = store.get_source(ev.source_id).local_identifier
    src = f"[{ident}]({ident})" if ident.startswith("http") else ident
    return f"„{ev.quote}” — {src}"


def facts_rows(store: ProvenanceStore, claim_ids: list[int]) -> list[list[str]]:
    """Claims table rows: kind, statement, verbatim grounds + position, surroundings,
    and external impact corroboration (empty = „—", i.e. none / not searched)."""
    rows: list[list[str]] = []
    for n, cid in enumerate(claim_ids, 1):
        claim = store.get_claim(cid)
        src = store.get_source(claim.source_id)
        evs = store.evidence_for_claim(cid)
        own = [e for e in evs if e.source_id == claim.source_id]
        ext = [e for e in evs if e.source_id != claim.source_id]
        cytat = " | ".join(f"„{e.quote}”" for e in own)
        pozycja = " | ".join(f"{e.start}–{e.end}" for e in own)
        kontekst = (
            _context_window(src.full_text, own[0].start, own[0].end) if own else ""
        )
        lead = store.get_lead(cid)
        slad = (
            f"🔍 {lead.query}"
            if lead is not None
            else _TRAIL_MARK.get(claim.external_trail, "—")
        )
        wplyw = " | ".join(_impact_cell(store, e) for e in ext) or "—"
        rows.append(
            [str(n), claim.kind, claim.statement, cytat, pozycja, kontekst, slad, wplyw]
        )
    return rows


def facts_csv(store: ProvenanceStore, claim_ids: list[int]) -> str:
    """Writes the claims table to CSV (a wide table is handier in a spreadsheet than in
    the browser). utf-8-sig BOM → Excel reads Polish characters correctly."""
    path = tempfile.NamedTemporaryFile(
        delete=False, suffix=".csv", prefix="facts_"
    ).name
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(FACTS_HEADERS)
        w.writerows(facts_rows(store, claim_ids))
    return path


def _run_phase(
    store: ProvenanceStore,
    skills: SkillRegistry,
    source_id: int,
    work_type: WorkType,
    llm: LLMClient,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Candidates:
    ctx = PhaseContext(store=store, llm=llm, skills=skills)
    phase = ExtractPhase(
        source_id,
        work_type,
        chunk_chars=settings.chunk_chars,
        on_progress=on_progress,
        should_stop=should_stop,
    )
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
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, Candidates]:
    source_id, _ = source_from_file(store, document, work_type)
    return source_id, _run_phase(
        store, skills, source_id, work_type, llm, on_progress, should_stop
    )


def extract_candidates_from_doi(
    store: ProvenanceStore,
    skills: SkillRegistry,
    doi: str,
    work_type: WorkType,
    llm: LLMClient,
    full_text: bool = False,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, Candidates]:
    fetched = fetch_by_doi(doi, contact_email=settings.contact_email)
    if full_text and fetched.oa_pdf_url:
        text = fetch_oa_fulltext(fetched.oa_pdf_url)
        if text:
            fetched = replace(fetched, full_text=text)
    source_id, _ = source_from_fetched(store, fetched)
    return source_id, _run_phase(
        store, skills, source_id, work_type, llm, on_progress, should_stop
    )


def extract_candidates_from_url(
    store: ProvenanceStore,
    skills: SkillRegistry,
    url: str,
    work_type: WorkType,
    llm: LLMClient,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, Candidates]:
    source_id, _ = source_from_url(store, url, work_type)
    return source_id, _run_phase(
        store, skills, source_id, work_type, llm, on_progress, should_stop
    )


def _source_preview(store: ProvenanceStore, source_id: int) -> str:
    """Human-readable summary of a loaded source, so the operator can confirm it is
    the right work (title, type, language, how much text) before extracting."""
    s = store.get_source(source_id)
    text = s.full_text or ""
    head = " ".join(text[:400].split())
    lines = [f"**Loaded source #{source_id}**"]
    if s.title:
        lines.append(f"- Title: {s.title}")
    if s.fabio_type:
        lines.append(f"- Type: {s.fabio_type.rsplit('/', 1)[-1]}")
    if s.language:
        lines.append(f"- Language: {s.language}")
    lines.append(f"- Identifier: {s.local_identifier}")
    lines.append(f"- Text length: {len(text)} chars")
    if head:
        lines.append(f"\n> {head}{'…' if len(text) > 400 else ''}")
    return "\n".join(lines)


def load_source(
    store: ProvenanceStore,
    mode: str,
    document: str | None,
    doi: str,
    url: str,
    work_type: WorkType,
    full_text: bool = False,
) -> tuple[int, str]:
    """Fetch/create the Source WITHOUT extracting, so the human reviews it first.
    Returns (source_id, preview markdown). Raises ValueError on missing input."""
    if mode == "DOI":
        if not doi.strip():
            raise ValueError("Provide a DOI.")
        fetched = fetch_by_doi(doi.strip(), contact_email=settings.contact_email)
        if full_text and fetched.oa_pdf_url:
            text = fetch_oa_fulltext(fetched.oa_pdf_url)
            if text:
                fetched = replace(fetched, full_text=text)
        sid, _ = source_from_fetched(store, fetched)
    elif mode == "URL":
        if not url.strip():
            raise ValueError("Provide a URL.")
        sid, _ = source_from_url(store, url.strip(), work_type)
    else:
        if not document:
            raise ValueError("Upload a document.")
        sid, _ = source_from_file(store, document, work_type)
    return sid, _source_preview(store, sid)


def apply_decisions(
    store: ProvenanceStore,
    all_ids: list[int],
    accepted_ids: list[int],
    by: str = "operator",
) -> tuple[int, int]:
    """Accepts the selected claims, rejects the rest."""
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
    """Builds FOR/AGAINST/GAPS arguments over the source's ACCEPTED claims."""
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
    by: str = "expert",
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
    # ponytail: one stop flag for the whole UI — enough with a single user
    #           (one operation at a time); per-operation if concurrency appears.
    stop_flag = threading.Event()

    def _llm(base_url: str, model: str) -> LLMClient:
        return LLMClient(
            base_url=base_url,
            api_key=settings.llm_api_key,
            model=model,
            temperature=settings.llm_temperature,
            json_mode=settings.llm_json_mode,
        )

    def on_load(mode, document, doi, url, full_text, work_type):  # type: ignore[no-untyped-def]
        # fetch/create the source WITHOUT extracting, so the human can review it first
        reset = gr.update(choices=[], value=[], visible=False)
        hide_table = gr.update(visible=False)
        try:
            sid, preview = load_source(
                store, mode, document, doi, url, WorkType(work_type), full_text
            )
        except Exception as e:  # noqa: BLE001
            return None, f"Error: {e}", reset, [], hide_table
        return sid, preview, reset, [], hide_table

    def on_extract(source_id, work_type, base_url, model):  # type: ignore[no-untyped-def]
        # generator: shows progress right away — extraction takes ~1-2 min (local model)
        empty = gr.update(choices=[], value=[], visible=False)
        keep = gr.skip()  # don't touch the claims table on early exits/ticks
        if not source_id:
            yield empty, [], "Fetch a source first.", keep
            return
        if not model:
            yield empty, [], "Provide the model name.", keep
            return
        wt = WorkType(work_type)
        llm = _llm(base_url, model)
        stop_flag.clear()
        prog: dict[str, str] = {"msg": ""}

        def note(m: str) -> None:
            prog["msg"] = m

        def work() -> Candidates:
            return _run_phase(
                store, skills, int(source_id), wt, llm, note, stop_flag.is_set
            )

        # extraction in a thread → generator refreshes the timer and stage every second
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["ok"] = work()
            except Exception as e:  # noqa: BLE001
                box["err"] = e

        th = threading.Thread(target=run)
        th.start()
        t0 = time.time()
        while th.is_alive():
            el = int(time.time() - t0)
            if stop_flag.is_set():
                msg = f"⏹ Stopping after the current chunk… ({el} s)"
            else:
                detail = f" — {prog['msg']}" if prog["msg"] else ""
                msg = f"⏳ Extracting facts… {el} s{detail}"
            # only the status ticks; we leave the claims list to not break its render
            yield gr.skip(), gr.skip(), msg, keep
            th.join(timeout=1.0)
        if "err" in box:
            yield empty, [], f"Error: {box['err']}", keep
            return
        cands = box["ok"]
        choices = [(label, cid) for cid, label in cands]
        ids = [cid for cid, _ in cands]
        table = gr.update(value=facts_rows(store, ids), visible=True)
        yield (
            gr.update(choices=choices, value=ids, visible=True),
            ids,
            f"Extracted {len(ids)}.",
            table,
        )

    def on_decide(selected, all_ids):  # type: ignore[no-untyped-def]
        acc, rej = apply_decisions(store, all_ids, selected)
        return f"Accepted {acc} facts, rejected {rej}."

    def on_argue(source_id, base_url, model):  # type: ignore[no-untyped-def]
        empty = gr.update(choices=[], value=[], visible=False)
        if not source_id:
            return empty, [], "First extract and approve facts."
        try:
            llm = _llm(base_url, model)
            args = argue_candidates(store, skills, int(source_id), llm)
        except Exception as e:  # noqa: BLE001
            return empty, [], f"Error: {e}"
        if not args:
            return empty, [], "No arguments (approve facts first)."
        choices = [(label, aid) for aid, label in args]
        ids = [aid for aid, _ in args]
        msg = f"Built {len(ids)} arguments."
        return gr.update(choices=choices, value=ids, visible=True), ids, msg

    def on_decide_args(selected, all_ids):  # type: ignore[no-untyped-def]
        acc, rej = apply_argument_decisions(store, all_ids, selected)
        return f"Accepted {acc} arguments, rejected {rej}."

    def on_corroborate(source_id, base_url, model):  # type: ignore[no-untyped-def]
        keep = gr.skip()  # don't touch the table during progress
        if not source_id:
            yield "First extract and approve facts.", keep
            return
        claims = store.claims_for_source(int(source_id), status="accepted")
        if not claims:
            yield "No approved facts — approve facts first.", keep
            return
        accepted_ids = [c.id for c in claims if c.id is not None]

        def table_now() -> Any:
            return gr.update(value=facts_rows(store, accepted_ids), visible=True)

        llm = _llm(base_url, model)
        stop_flag.clear()
        activity = f"corroborate:{source_id}"
        context = study_context(store.get_source(int(source_id)))
        yield "⏳ Searching for leads (what to look for as impact evidence)…", keep
        run_suggester(
            store, llm, skills, int(source_id)
        )  # saves query + trail per fact
        # table immediately shows the trail marks (candidate/internal) and queries
        yield "⏳ Leads saved — searching for corroboration…", table_now()
        # search EVERY fact; the 'internal' trail is only a hint, not a filter
        targets = [c for c in claims if c.id is not None]
        lines: list[str] = []
        for i, claim in enumerate(targets, 1):
            if stop_flag.is_set():
                yield (
                    "\n".join([*lines, f"⏹ Stopped ({i - 1}/{len(targets)})."]),
                    table_now(),
                )
                return
            lead = store.get_lead(claim.id) if claim.id is not None else None
            q = lead.query if lead is not None else claim.statement
            prog = (
                f"⏳ Checking {i}/{len(targets)}: {claim.statement[:55]}…\n    🔍 {q}"
            )
            yield "\n".join([*lines, prog]), keep
            try:
                eid = corroborate_one(
                    store,
                    llm,
                    claim,
                    query=lead.query if lead is not None else None,
                    context=context,
                    activity=activity,
                    agent=llm.model,
                )
            except Exception as e:  # noqa: BLE001
                yield "\n".join([*lines, f"⚠️ error on fact {i}: {e}"]), keep
                continue
            if eid is not None:
                ev = store.get_evidence(eid)
                src = store.get_source(ev.source_id)
                lines.append(f"- ✅ **{claim.statement}**")
                lines.append(f"    „{ev.quote}” — {src.local_identifier}")
        msg = "\n".join(lines) if lines else "No corroboration found on the web."
        yield msg, table_now()

    def on_stop():  # type: ignore[no-untyped-def]
        # cooperative stop: extraction finishes the current chunk, corroboration the
        # current claim (a model call can't be interrupted mid-flight), then halts.
        stop_flag.set()
        return "⏹ Stopping…", "⏹ Stopping…"

    with gr.Blocks(title="IMeTo") as ui:
        gr.Markdown("# IMeTo")
        gr.Markdown(
            "Facts grounded in the source → impact corroboration on the web "
            "→ assessment by Criterion III"
        )

        with gr.Accordion("Model settings", open=False):
            base_url = gr.Textbox(label="Model address", value=settings.llm_base_url)
            model = gr.Textbox(label="Model", value=settings.llm_model)

        gr.Markdown("## Source")
        mode = gr.Radio(choices=["File", "DOI", "URL"], value="File", label="Mode")
        document = gr.File(label="Document (PDF/DOCX)", type="filepath")
        work_type = gr.Dropdown(
            label="Work type",
            choices=[wt.value for wt in WorkType],
            value=WorkType.report.value,
        )
        doi = gr.Textbox(label="DOI", placeholder="10.1234/...")
        url = gr.Textbox(label="URL", placeholder="https://...")
        full_text = gr.Checkbox(label="OA full text", value=False)
        load_btn = gr.Button("Fetch source", variant="primary")
        source_preview = gr.Markdown()

        gr.Markdown("## Step 1 · Facts")
        extract_btn = gr.Button("Extract facts from source", variant="primary")
        candidates = gr.CheckboxGroup(
            label="Select to accept", choices=[], visible=False
        )
        decide_btn = gr.Button("Approve selected facts")
        status = gr.Markdown()
        facts_table = gr.Dataframe(
            headers=FACTS_HEADERS,
            datatype=FACTS_DATATYPES,
            column_widths=FACTS_WIDTHS,
            label="Facts with provenance and context",
            interactive=False,
            wrap=True,
            visible=False,
        )
        download_btn = gr.DownloadButton("Download table (CSV)")

        gr.Markdown("## Step 2 · Impact corroboration on the web")
        corroborate_btn = gr.Button("Corroborate facts on the web")
        corr_output = gr.Markdown()

        gr.Markdown("## Step 3 · Assessment by Criterion III")
        argue_btn = gr.Button("Assess by Criterion III", variant="primary")
        arguments = gr.CheckboxGroup(
            label="Select to accept", choices=[], visible=False
        )
        decide_args_btn = gr.Button("Approve selected arguments")
        arg_status = gr.Markdown()

        stop_btn = gr.Button("Stop")

        source_id = gr.State(None)
        all_ids = gr.State([])
        arg_ids = gr.State([])

        load_btn.click(
            on_load,
            [mode, document, doi, url, full_text, work_type],
            [source_id, source_preview, candidates, all_ids, facts_table],
        )
        extract_btn.click(
            on_extract,
            [source_id, work_type, base_url, model],
            [candidates, all_ids, status, facts_table],
        )
        decide_btn.click(on_decide, [candidates, all_ids], [status])
        download_btn.click(lambda ids: facts_csv(store, ids), all_ids, download_btn)
        ev_argue = argue_btn.click(
            on_argue, [source_id, base_url, model], [arguments, arg_ids, arg_status]
        )
        decide_args_btn.click(on_decide_args, [arguments, arg_ids], [arg_status])
        ev_corr = corroborate_btn.click(
            on_corroborate, [source_id, base_url, model], [corr_output, facts_table]
        )
        # extraction stops cooperatively (thread + flag) — we do NOT cancel its
        # generator, since only it shows closure. Corroboration/scoring we also cancel.
        stop_btn.click(
            on_stop, None, [status, corr_output], cancels=[ev_corr, ev_argue]
        )
    return ui


def launch() -> None:
    build_ui().queue().launch()


if __name__ == "__main__":
    launch()
