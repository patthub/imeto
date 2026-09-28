# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Pre-implementation. The repo currently contains only `TECHNICZNY.md` (a Polish
Technical Design Document) and an empty `.venv`. **No source code, `pyproject.toml`,
or tests exist yet** — most files the TDD marks as "**istnieje**" are still planned.
When you write code, you are bootstrapping against the design in `TECHNICZNY.md`, not
modifying existing modules. Read it before making structural decisions.

## What IMeTo is

A single-user, on-premise-friendly pipeline that extracts factual claims from documents
(PDF/DOCX), anchors every claim to verbatim source evidence (provenance), and runs them
through human-gated phases (extract → suggest → argue → write → export). The core value is
**anti-hallucination via provenance**: no claim enters the store without a verified,
character-exact span in its source.

## Planned architecture (from TECHNICZNY.md §4–6)

- **`core/`** — shared kernel: `llm.py` (model-agnostic OpenAI-compatible client + validate/retry loop), `schemas.py` (Pydantic structured-output models), `provenance.py` (`ProvenanceStore`), `span.py` (verbatim quote verification).
- **`phases/`** — pipeline stages, each implementing the `Phase` protocol (`run(ctx) -> PhaseResult`). Phases depend on `core/`, **never the reverse** — this boundary is hard.
- **`orchestration/`** — explicit linear pipeline (`PIPELINE = [...]` list, no `while True`); `gates.py` blocks for human approval when `PhaseResult.needs_human`.
- **`registries/`** — pluggable `ToolRegistry`, `SkillRegistry`, `PhaseRegistry`.
- **`knowledge/`** — domain expertise as **data** (`.md` files, few-shot examples), editable without touching code. Loaded into prompts on demand via `SkillRegistry`. Not code, not constants.
- **`ui/`** — web GUI: `app.py` (framework-free views + phases as progress-event generators), `server.py` (FastAPI, NDJSON streaming); the front lives in `web/` (React 19 + Vite + Tailwind v4 + shadcn/ui, TanStack Query). Thin skins that call the core. Never put phase logic in route handlers or React components.

## Non-negotiable rules (from the TDD)

- **Sync core, async only at the API edge.** The kernel (phases, provenance, extraction) is synchronous. Introduce async *only* in the FastAPI layer, and only if real concurrency appears.
- **Model-agnostic.** Only touch point with any model is OpenAI Chat Completions via `LLM_BASE_URL` / `LLM_MODEL`. No provider-locking SDKs (no Anthropic/Bedrock/LangChain/LlamaIndex) — swapping models must require zero code change.
- **All DB access goes through `ProvenanceStore`.** No other module touches SQL. This keeps the SQLite→Postgres path (SQLModel, one model definition for both engines) cheap. Avoid sqlite-isms; `meta` fields are JSON (→ JSONB on Postgres).
- **Provenance invariants live in code, not just schema.** `add_evidence` accepts a record only after span verification. Anti-hallucination logic is pure Python over `full_text`/`quote` — engine-independent.
- **Tools return candidates, not verdicts.** A human decides what is evidence. Any tool output that becomes evidence goes through the same source/evidence gate as extraction.
- **Config is typed and centralized** in `config.py` (`pydantic-settings`), not scattered `os.getenv`. Secrets only from env/`.env`.
- **Every core module has a test that runs without a live model** — mock the LLM (respx / stub responses). Model quality is measured separately via eval, not unit tests.
- Deferred by design (do not introduce early): Alembic (POC uses `SQLModel.metadata.create_all`), Postgres/psycopg, `sentence-transformers`. See TDD §3.3–3.4.

## Planned stack

Python 3.12+ · Pydantic v2 · `openai` SDK (+ httpx) · SQLModel over SQLite · pdfplumber /
python-docx · Typer (CLI) · FastAPI + React/Vite front (`web/`) · pytest + respx · ruff + mypy · uv for env/lock.

Note: the current `.venv` is Python 3.14 with only pip. Recreate per the target when scaffolding.

## Commands (once scaffolded per TDD §13)

```bash
uv sync                       # core + SQLite;  --extra ui | mcp | postgres | dev for variants
export LLM_BASE_URL=http://localhost:8888/v1
export LLM_API_KEY=sk-...
export LLM_MODEL="<id from /v1/models>"
python -m imeto.cli run data/sprawozdanie_test.docx

imeto ui                      # GUI at http://127.0.0.1:8000 (needs: cd web && npm i && npm run build)
cd web && npm run dev         # front dev server with HMR, proxies /api to :8000

pytest                        # all tests
pytest tests/test_span_verification.py::<name>   # single test
ruff check . && ruff format . # lint + format
mypy imeto                    # type check
```

## Language note

`TECHNICZNY.md` and the domain (`knowledge/`, rubric files) are in Polish. Code identifiers
and comments in the doc's sketches mix Polish and English — match the surrounding file's
convention when editing.
