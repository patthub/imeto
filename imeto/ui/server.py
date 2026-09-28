"""HTTP skin over `imeto.ui.app` for the React front (`web/`). Thin by rule: no phase
logic here, only request parsing and streaming.

Sync handlers on purpose (sync core, §3): FastAPI runs them in its threadpool. Long
operations stream NDJSON progress events; the front reads them with fetch."""

import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from imeto.config import settings
from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore
from imeto.registries.skills import SkillRegistry
from imeto.tools.signals import find_entities
from imeto.ui import app as logic
from imeto.worktypes import WorkType

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

MakeLLM = Callable[[str, str], LLMClient]


class ModelIn(BaseModel):
    base_url: str = ""
    model: str = ""


class ClaimPatch(BaseModel):
    accepted: bool | None = None
    query: str | None = None


class ArgumentPatch(BaseModel):
    accepted: bool | None = None
    sphere: str | None = None  # "" clears


def create_app(
    store: ProvenanceStore,
    skills: SkillRegistry,
    make_llm: MakeLLM,
    upload_dir: Path,
    web_dist: Path = WEB_DIST,
) -> FastAPI:
    api = FastAPI(title="IMeTo")
    # ponytail: one stop flag for the whole app — one operator, one operation at a
    #           time; per-operation flags if concurrency appears.
    stop = threading.Event()

    def llm_of(m: ModelIn) -> LLMClient:
        model = m.model or settings.llm_model
        if not model:
            raise HTTPException(400, "Set the model name in Settings.")
        return make_llm(m.base_url or settings.llm_base_url, model)

    def stream(events: Iterator[logic.Event]) -> StreamingResponse:
        def lines() -> Iterator[str]:
            try:
                for ev in events:
                    yield json.dumps(ev, ensure_ascii=False) + "\n"
            except Exception as e:  # noqa: BLE001 — surfaced in the UI, not a 500
                yield json.dumps({"error": str(e)}, ensure_ascii=False) + "\n"

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    def source_or_404(sid: int) -> dict[str, Any]:
        try:
            return logic.source_view(store, sid)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e

    @api.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "work_types": [wt.value for wt in WorkType],
        }

    @api.get("/api/sources")
    def sources() -> list[dict[str, Any]]:
        return logic.sources_list(store)

    @api.post("/api/sources")
    def add_source(
        mode: Annotated[str, Form()] = "File",
        work_type: Annotated[WorkType, Form()] = WorkType.report,
        doi: Annotated[str, Form()] = "",
        url: Annotated[str, Form()] = "",
        full_text: Annotated[bool, Form()] = False,
        file: Annotated[UploadFile | None, File()] = None,
    ) -> dict[str, int]:
        path = None
        if mode == "File" and file is not None and file.filename:
            # kept under its own name: the path is the source's identifier (and title)
            dest = upload_dir / Path(file.filename).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(file.file.read())
            path = str(dest)
        try:
            sid = logic.load_source(store, mode, path, doi, url, work_type, full_text)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"id": sid}

    @api.get("/api/sources/{sid}")
    def source(sid: int) -> dict[str, Any]:
        return source_or_404(sid)

    @api.post("/api/sources/{sid}/signals")
    def refresh_signals(sid: int) -> dict[str, Any]:
        try:
            return {"signals": logic.refresh_signals(store, sid)}
        except ValueError as e:
            raise HTTPException(404, str(e)) from e

    def leads(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @api.get("/api/leads/search")
    def leads_search(q: str, kind: str = "institution") -> list[dict[str, Any]]:
        return find_entities(q, kind, params=settings.openalex_params)

    @api.get("/api/leads/{entity}/partners")
    def leads_partners(entity: str) -> Any:
        return leads(lambda: logic.leads_partners(entity))

    @api.get("/api/leads/{entity}/partners/{partner}")
    def leads_partner_works(entity: str, partner: str) -> Any:
        return leads(lambda: logic.leads_partner_works(entity, partner))

    @api.get("/api/leads/{entity}/reports")
    def leads_reports(entity: str) -> Any:
        return leads(lambda: logic.leads_reports(entity))

    @api.get("/api/leads/{entity}/citing")
    def leads_citing(entity: str) -> Any:
        return leads(lambda: logic.leads_citing(entity))

    @api.post("/api/leads/{entity}/case/{citing}")
    def leads_case(entity: str, citing: str, via: str = "") -> Any:
        return leads(lambda: {"id": logic.build_case(store, entity, citing, via)})

    @api.get("/api/leads/{entity}/citing/{org}")
    def leads_citing_works(entity: str, org: str) -> Any:
        return leads(lambda: logic.leads_citing_works(entity, org))

    @api.get("/api/sources/{sid}/facts.csv")
    def facts_csv(sid: int) -> FileResponse:
        ids = [c.id for c in logic.visible_claims(store, sid) if c.id is not None]
        return FileResponse(
            logic.facts_csv(store, ids),
            media_type="text/csv",
            filename=f"facts_source_{sid}.csv",
        )

    @api.post("/api/sources/{sid}/accept-all")
    def accept_all(sid: int) -> dict[str, Any]:
        for c in logic.visible_claims(store, sid):
            if c.id is not None:
                logic.set_accepted(store, c.id, True)
        return source_or_404(sid)

    @api.patch("/api/claims/{cid}")
    def patch_claim(cid: int, body: ClaimPatch) -> dict[str, bool]:
        if body.accepted is not None:
            logic.set_accepted(store, cid, body.accepted)
        if body.query is not None:
            logic.save_query(store, cid, body.query)
        return {"ok": True}

    @api.patch("/api/arguments/{aid}")
    def patch_argument(aid: int, body: ArgumentPatch) -> dict[str, bool]:
        try:
            if body.accepted is not None:
                logic.set_argument_accepted(store, aid, body.accepted)
            if body.sphere is not None:
                logic.set_argument_sphere(store, aid, body.sphere)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True}

    phases = {
        "extract": logic.extract_events,
        "suggest": logic.suggest_events,
        "corroborate": logic.corroborate_events,
    }

    @api.post("/api/sources/{sid}/run/{phase}")
    def run(sid: int, phase: str, body: ModelIn) -> StreamingResponse:
        if phase == "argue":  # one model call, no progress to stream
            llm = llm_of(body)

            def argue() -> Iterator[logic.Event]:
                yield {"status": "Assessing by Criterion III"}
                n = len(logic.argue_candidates(store, skills, sid, llm))
                yield {"log": f"Built {n} arguments."}

            return stream(argue())
        if phase not in phases:
            raise HTTPException(404, f"unknown phase {phase}")
        source_or_404(sid)
        stop.clear()
        return stream(phases[phase](store, skills, sid, llm_of(body), stop))

    @api.post("/api/stop")
    def stop_all() -> dict[str, bool]:
        stop.set()
        return {"ok": True}

    # the built front; client-side routes (/sources/3) fall back to index.html
    @api.get("/{path:path}", include_in_schema=False)
    def front(path: str) -> FileResponse:
        file = (web_dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(web_dist.resolve()):
            return FileResponse(file)
        index = web_dist / "index.html"
        if not index.is_file():
            raise HTTPException(404, "Front not built — run `npm run build` in web/.")
        # always revalidated: it names the hashed bundles, so a stale copy runs old code
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return api


def launch(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    def make_llm(base_url: str, model: str) -> LLMClient:
        return LLMClient(
            base_url=base_url,
            api_key=settings.llm_api_key,
            model=model,
            temperature=settings.llm_temperature,
            json_mode=settings.llm_json_mode,
        )

    api = create_app(
        ProvenanceStore(settings.db_url),
        SkillRegistry(settings.knowledge_dir),
        make_llm,
        Path(settings.upload_dir),
    )
    uvicorn.run(api, host=host, port=port)
