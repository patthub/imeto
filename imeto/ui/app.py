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
from imeto.phases.corroborate import citations_for, corroborate_one
from imeto.phases.extract import ExtractPhase
from imeto.phases.suggest import iter_suggester, study_context
from imeto.registries.skills import SkillRegistry
from imeto.tools.citations import doi_of
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
    """ "Impact" cell: quote + source as a clickable link when it's a URL. The channel
    marker matters for judging: 📚 = a work that CITES this study (it demonstrably used
    it), 🔍 = a page a keyword search turned up."""
    ident = store.get_source(ev.source_id).local_identifier
    src = f"[{ident}]({ident})" if ident.startswith("http") else ident
    act = ev.generated_by_activity or ""
    mark = "📚 cited by" if act.endswith(":citation") else "🔍 web"
    return f"{mark}: „{ev.quote}” — {src}"


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


def save_query(store: ProvenanceStore, claim_id: int, query: str) -> bool:
    """Writes a query edited on the fact's card. The query is a CANDIDATE (Z1) — the
    human owns it. Emptied → the lead is cleared and corroboration falls back to the
    fact's own text. Returns whether a query is now stored."""
    q = query.strip()
    if not q:
        store.clear_lead(claim_id)
        return False
    lead = store.get_lead(claim_id)
    store.upsert_lead(claim_id, lead.lead if lead is not None else "", q)
    return True


def set_accepted(store: ProvenanceStore, claim_id: int, accepted: bool) -> None:
    """The human gate, toggled straight on the fact's card."""
    if accepted:
        store.accept_claim(claim_id, by="operator")
    else:
        store.reject_claim(claim_id, by="operator")


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

    # `tick` (gr.State) is bumped whenever the fact cards must be rebuilt from the
    # store; @gr.render below re-runs on its change. We do NOT bump it mid-stream —
    # rebuilding the cards would wipe a query the human is editing.
    def on_load(mode, document, doi, url, full_text, work_type, tick):  # type: ignore[no-untyped-def]
        # fetch/create the source WITHOUT extracting, so the human can review it first
        try:
            sid, preview = load_source(
                store, mode, document, doi, url, WorkType(work_type), full_text
            )
        # all_ids changes by itself → the render fires; skip the tick or it fires twice
        except Exception as e:  # noqa: BLE001
            return None, f"Error: {e}", [], gr.skip()
        return sid, preview, [], gr.skip()

    def on_extract(source_id, work_type, base_url, model, tick):  # type: ignore[no-untyped-def]
        # generator: shows progress right away — extraction takes ~1-2 min (local model)
        keep = gr.skip()  # don't touch the cards on early exits/ticks
        if not source_id:
            yield "Fetch a source first.", keep, keep
            return
        if not model:
            yield "Provide the model name.", keep, keep
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
            yield msg, keep, keep  # only the status ticks; cards stay as they are
            th.join(timeout=1.0)
        if "err" in box:
            yield f"Error: {box['err']}", [], keep
            return
        ids = [cid for cid, _ in box["ok"]]
        yield f"Extracted {len(ids)} facts — tick the ones you keep.", ids, keep

    def on_accept_all(ids, tick):  # type: ignore[no-untyped-def]
        for cid in ids:
            set_accepted(store, cid, True)
        return f"Approved {len(ids)} facts (untick any on its card).", tick + 1

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

    def on_suggest(source_id, base_url, model, tick):  # type: ignore[no-untyped-def]
        # proposes a query per fact and STOPS — the human reviews/edits before searching
        keep = gr.skip()
        if not source_id:
            yield "First extract and approve facts.", keep
            return
        claims = store.claims_for_source(int(source_id), status="accepted")
        if not claims:
            yield "No approved facts — tick facts on their cards first.", keep
            return
        n = len(claims)
        stop_flag.clear()
        yield f"⏳ Proposing queries for {n} facts…", keep
        try:  # one model call per fact — a batched one overruns the timeout
            for i, _ in enumerate(
                iter_suggester(store, _llm(base_url, model), skills, int(source_id)), 1
            ):
                yield f"⏳ Proposing queries… {i}/{n}", keep
                if stop_flag.is_set():
                    break
        except Exception as e:  # noqa: BLE001
            yield f"Error: {e}", tick + 1
            return
        yield "Queries proposed — edit them on the cards, then corroborate.", tick + 1

    def on_corroborate(source_id, base_url, model, tick):  # type: ignore[no-untyped-def]
        keep = gr.skip()  # don't rebuild the cards during progress
        if not source_id:
            yield "First extract and approve facts.", keep
            return
        claims = store.claims_for_source(int(source_id), status="accepted")
        if not claims:
            yield "No approved facts — tick facts on their cards first.", keep
            return
        llm = _llm(base_url, model)
        stop_flag.clear()
        activity = f"corroborate:{source_id}"
        src = store.get_source(int(source_id))
        context = study_context(src)
        yield "⏳ Asking OpenAlex who cites this work…", keep
        citing = citations_for(src)  # once per source, reused for every fact
        if citing:
            found = "\n".join(f"    📚 {c.title[:70]} — {c.url}" for c in citing)
            head = f"📚 {len(citing)} citing works (checked before the search engine):"
            yield f"{head}\n{found}", keep
        else:
            why = "no DOI" if doi_of(src) is None else "none found"
            yield f"📚 Citation channel: {why} — searching the web only.", keep
        targets = [c for c in claims if c.id is not None]
        # queries come from the cards; none stored → the human skipped the propose
        # step, so propose them here (one click still works end to end)
        if not any(store.get_lead(cid) for cid in [c.id for c in targets] if cid):
            for i, _ in enumerate(
                iter_suggester(store, llm, skills, int(source_id)), 1
            ):
                yield f"⏳ Proposing search queries… {i}/{len(targets)}", keep
                if stop_flag.is_set():
                    break
        lines: list[str] = []
        for i, claim in enumerate(targets, 1):
            if stop_flag.is_set():
                stopped = f"⏹ Stopped ({i - 1}/{len(targets)})."
                yield "\n".join([*lines, stopped]), tick + 1
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
                    citing=citing,
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
        yield msg, tick + 1  # cards now show the ✅ evidence

    def fact_card(n: int, cid: int) -> None:
        """One fact, one card: the gate, its verbatim grounds, the editable query and
        what the web turned up — instead of the same fact spread over three tables."""
        claim = store.get_claim(cid)
        src = store.get_source(claim.source_id)
        evs = store.evidence_for_claim(cid)
        own = [e for e in evs if e.source_id == claim.source_id]
        ext = [e for e in evs if e.source_id != claim.source_id]
        lead = store.get_lead(cid)
        with gr.Group():
            gate = gr.Checkbox(
                value=claim.status == "accepted",
                label=f"#{n} · {claim.kind} · {claim.statement}",
                container=False,
            )
            if own:
                gr.Markdown(
                    "  \n".join(f"„{e.quote}” · {e.start}–{e.end}" for e in own)
                )
                with gr.Accordion("Context in source", open=False):
                    gr.Markdown(
                        _context_window(src.full_text, own[0].start, own[0].end)
                    )
            query = gr.Textbox(
                value=lead.query if lead is not None else "",
                label="🔍 Search query (editable; empty = search by the fact's text)",
                lines=1,
            )
            if ext:
                gr.Markdown("  \n".join(f"✅ {_impact_cell(store, e)}" for e in ext))
            elif claim.external_trail == "internal":
                gr.Markdown("*no external trail expected (model's hint)*")
            # written straight through — no separate "save" button to forget
            gate.change(lambda v, c=cid: set_accepted(store, c, bool(v)), inputs=gate)
            query.blur(lambda v, c=cid: save_query(store, c, v), inputs=query)

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

        source_id = gr.State(None)
        all_ids = gr.State([])
        arg_ids = gr.State([])
        tick = gr.State(0)  # bump = rebuild the fact cards from the store

        with gr.Row():
            with gr.Column(scale=2):  # controls — every button lives here
                with gr.Accordion("Model settings", open=False):
                    base_url = gr.Textbox(
                        label="Model address", value=settings.llm_base_url
                    )
                    model = gr.Textbox(label="Model", value=settings.llm_model)

                gr.Markdown("### Source")
                mode = gr.Radio(
                    choices=["File", "DOI", "URL"], value="File", label="Mode"
                )
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

                gr.Markdown("### Step 1 · Facts")
                extract_btn = gr.Button("Extract facts from source", variant="primary")
                accept_all_btn = gr.Button("Approve all facts")
                status = gr.Markdown()
                download_btn = gr.DownloadButton("Download table (CSV)")

                gr.Markdown("### Step 2 · Impact corroboration on the web")
                suggest_btn = gr.Button("Propose search queries")
                corroborate_btn = gr.Button("Corroborate facts on the web")
                lead_status = gr.Markdown()
                corr_output = gr.Markdown()

                gr.Markdown("### Step 3 · Assessment by Criterion III")
                argue_btn = gr.Button("Assess by Criterion III", variant="primary")

                stop_btn = gr.Button("Stop")

            with gr.Column(scale=3):  # one card per fact, nothing duplicated
                gr.Markdown("### Facts")

                @gr.render(inputs=[all_ids, tick])  # type: ignore[untyped-decorator]
                def render_facts(ids: list[int], _tick: int) -> None:
                    if not ids:
                        gr.Markdown("*Fetch a source and extract to see facts here.*")
                        return
                    for n, cid in enumerate(ids, 1):
                        fact_card(n, cid)

                gr.Markdown("### Assessment")
                arguments = gr.CheckboxGroup(
                    label="Select to accept", choices=[], visible=False
                )
                decide_args_btn = gr.Button("Approve selected arguments")
                arg_status = gr.Markdown()

        load_btn.click(
            on_load,
            [mode, document, doi, url, full_text, work_type, tick],
            [source_id, source_preview, all_ids, tick],
        )
        extract_btn.click(
            on_extract,
            [source_id, work_type, base_url, model, tick],
            [status, all_ids, tick],
        )
        accept_all_btn.click(on_accept_all, [all_ids, tick], [status, tick])
        download_btn.click(lambda ids: facts_csv(store, ids), all_ids, download_btn)
        ev_argue = argue_btn.click(
            on_argue, [source_id, base_url, model], [arguments, arg_ids, arg_status]
        )
        decide_args_btn.click(on_decide_args, [arguments, arg_ids], [arg_status])
        ev_suggest = suggest_btn.click(
            on_suggest, [source_id, base_url, model, tick], [lead_status, tick]
        )
        ev_corr = corroborate_btn.click(
            on_corroborate, [source_id, base_url, model, tick], [corr_output, tick]
        )
        # extraction stops cooperatively (thread + flag) — we do NOT cancel its
        # generator, since only it shows closure. Corroboration/scoring we also cancel.
        stop_btn.click(
            on_stop,
            None,
            [status, corr_output],
            cancels=[ev_corr, ev_argue, ev_suggest],
        )
    return ui


def launch() -> None:
    build_ui().queue().launch()


if __name__ == "__main__":
    launch()
