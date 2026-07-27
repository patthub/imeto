# IMeTo — Technical Document (stack, libraries, structure)

> A complement to `ARCHITEKTURA.md`. That document answers the question **"how is this laid
> out and why"**; this one answers **"what exactly to build it from"** — the stack, the
> libraries with versions and rationale, the target directory structure, module contracts,
> working conventions.

| | |
|---|---|
| **Document** | Technical Design Document (TDD) |
| **Scope** | IMeTo — minimum plan (POC-1 → POC-3) |
| **Doc version** | 0.1 (draft) |
| **Related** | `ARCHITEKTURA.md` (SAD), `IMeTo_Plan_minimum` |
| **Library versions updated** | June 2026 |

---

## Table of contents

1. [Assumptions and technology-selection principles](#1-assumptions-and-technology-selection-principles)
2. [Technology stack — overview](#2-technology-stack-overview)
3. [Libraries — choice, versions, rationale](#3-libraries-choice-versions-rationale)
4. [Target directory structure](#4-target-directory-structure)
5. [Module contracts (interfaces)](#5-module-contracts-interfaces)
6. [Implementation patterns and ideas](#6-implementation-patterns-and-ideas)
7. [Configuration and secrets](#7-configuration-and-secrets)
8. [LLM layer — technical details](#8-llm-layer-technical-details)
9. [Data layer — technical details](#9-data-layer-technical-details)
10. [Tools and MCP](#10-tools-and-mcp)
11. [Testing and code quality](#11-testing-and-code-quality)
12. [Observability and evaluation](#12-observability-and-evaluation)
13. [Packaging, running, deployment](#13-packaging-running-deployment)
14. [Full dependency list](#14-full-dependency-list)
15. [POC → application migration plan](#15-poc-application-migration-plan)

---

## 1. Assumptions and technology-selection principles
<a id="1-assumptions-and-technology-selection-principles"></a>

The technology choices follow directly from the architecture principles and constraints
(see SAD §2–3):

- **Boring = good.** We pick mature, widely used libraries with a stable API. A POC for a
  single user is no place for exotica.
- **Minimal dependencies.** Every library is debt. Default to stdlib; external ones only
  where they deliver real value (parsing, validation, the LLM client).
- **Model-agnosticism (R-swap).** No SDK that locks us to a single model provider.
- **No agent framework (ADR-005).** Orchestration is our own, readable code.
- **On-premise-friendly (NFR-M-007).** Everything must work without the cloud and without
  SaaS services.
- **Synchronous in the core.** The minimum plan's profile (single user, linear pipeline, one
  model call at a time) gains nothing from async, while async costs readability and
  debuggability. The core (phases, provenance, extraction) is synchronous. We introduce
  async **only** in the API layer (FastAPI), if and when real concurrency appears.

---

## 2. Technology stack — overview
<a id="2-technology-stack-overview"></a>

```
Language       Python 3.12+            (match statements, better types, performance)
Validation     Pydantic v2             (enforceable structured output)
LLM client     openai SDK (OpenAI-compatible)  + httpx underneath
Data           SQLite via SQLModel      (engine swappable to Postgres without changing models)
Parsing        pdfplumber, python-docx
Concurrency    SYNCHRONOUS in the core (async only in the API layer, when/if needed)
HTTP/tools     httpx + MCP (ssh_connectors) for metadata anchors
GUI            Gradio (first GUI, human gates) → FastAPI when an API is needed
Configuration  pydantic-settings + .env
Testing        pytest                  (+ respx for mocking HTTP)
Quality        ruff (lint+format), mypy (types)
Packaging      uv / pip + pyproject.toml
Observability  stdlib logging → optionally structlog; own golden-set eval
```

**Three decisions worth highlighting (made deliberately, not by default):**

1. **SQLite via SQLModel, not bare sqlite3, not Postgres.** The minimum plan's profile is a
   single user, locally, with on-prem still distant — SQLite is right here (zero
   administration, "run and it works"). The "headroom for the future" comes from **the
   architecture, not the database engine**: SQLModel defines the models once and works on
   both SQLite and Postgres; all access goes through `ProvenanceStore`. Migrating to Postgres,
   when on-prem becomes real, is a connection-string change + a data migration, not a rewrite
   (see [§9.4 Postgres migration path](#94-postgres-migration-path)).
2. **Synchronous core.** The load profile (single user, linear pipeline, one model call at a
   time) gains nothing from async, while async costs readability and debuggability. We
   introduce async **only** in the API layer (FastAPI), if and when real concurrency appears.
   The core (phases, provenance, extraction) stays sync.
3. **Gradio as the first GUI.** For piloting and realizing human gates (show candidates →
   accept/reject → the pipeline moves on), Gradio gives a clickable interface at a fraction of
   the effort of a full frontend. We add FastAPI only when a real API/integration is needed.
   **The overriding rule:** the GUI is a thin skin calling the core — logic is never in UI
   callbacks.

The "in the POC → in the application" layering is deliberate: the POC uses the lightest
variant (CLI/Gradio, SQLite), the application adds layers (FastAPI, possibly Postgres) without
changing the core.

---

## 3. Libraries — choice, versions, rationale
<a id="3-libraries-choice-versions-rationale"></a>

> Versions current as of June 2026. We give lower bounds (`>=`), not hard pins — pins go into
> `uv.lock` / `requirements.lock` at deployment.

### 3.1 Core (required from POC-1)

| Library | Version | Role | Why this one |
|---|---|---|---|
| **pydantic** | `>=2.9` | Structured-output validation, data models | De facto standard; v2 is fast, enforces the format contract (ADR-003). Currently 2.13.x |
| **openai** | `>=1.30` | OpenAI-compatible client (Unsloth/vLLM/partner) | Model-agnosticism: the same code for local and on-prem (ADR-002) |
| **httpx** | `>=0.27` | HTTP transport (under openai + our own tools) | Async, modern; pulled in by the openai SDK anyway |
| **pdfplumber** | `>=0.11` | PDF parsing preserving content | Good text/layout extraction; key for verbatim quotes (ADR-004) |
| **python-docx** | `>=1.1` | DOCX parsing/generation | Standard for .docx; also used for the test document |
| **sqlmodel** | `>=0.0.22` | ORM over SQLite (engine swappable to Postgres) | Pydantic + SQLAlchemy in one; data models = validation models. Defined once → SQLite and Postgres |
| **pydantic-settings** | `>=2.0` | Configuration from env/.env | Consistent with Pydantic; typed config instead of `os.getenv` scattered across the code |

> **A note on httpx.** In 2026 Pydantic Services took over maintenance of httpx, also
> publishing it as the `httpx2` package (import `httpx2`) with a maintenance and
> security-update guarantee. The API is compatible. **Recommendation:** stay with `httpx`
> (lower risk, pulled in by the openai SDK); consider `httpx2` only if you care about the
> latest security patches and control the whole dependency graph.

### 3.2 Application (from the point where the CLI no longer suffices)

| Library | Version | Role | Why this one |
|---|---|---|---|
| **gradio** | `>=4.0` | First GUI: pilot + human gates | A clickable interface (accept/reject candidates) at a fraction of frontend effort; ideal for human-in-the-loop |
| **typer** | `>=0.12` | CLI (operations, tests, automation) | Builds a CLI from type hints; less boilerplate than argparse; consistent with Pydantic |
| **fastapi** | `>=0.115` | HTTP API — only when integration is needed | Mature, async, auto-schema from Pydantic. Currently 0.136.x (Starlette 1.0). This is where async enters |
| **uvicorn** | `>=0.30` | ASGI server for FastAPI | The standard FastAPI runtime |
| **mcp** | `>=1.2` | MCP client for `ssh_connectors` (metadata anchors) | Consistency with the connectors already built |

### 3.3 Optional / future (do not introduce prematurely)

| Library | When | For what |
|---|---|---|
| **psycopg** (v3) | when on-prem → migration to Postgres | Postgres driver (sync and async); SQLModel works on it without changing models |
| **alembic** | at Postgres migration / a stable schema | Database migration versioning (in the SQLite POC, `create_all` suffices) |
| **sentence-transformers** | at the statement map (POC-3, level 2) | Embeddings for semantic sentence↔evidence coverage (locally) |
| **rapidfuzz** | if anchoring requires fuzzy matching | Fast text matching; carefully, so as not to let semantics in |
| **structlog** | when stdlib logs no longer suffice | Structured logging (decision tracing) |
| **respx** | LLM/HTTP layer tests | Mocking httpx without the network |

### 3.4 What we DELIBERATELY do NOT use (and why)

| Rejected | Reason |
|---|---|
| LangChain / LangGraph / LlamaIndex | Agent/RAG framework — at odds with the linear, human-gated flow (ADR-005). Reconsider only with an iterative argumenter |
| OpenHarness and related harnesses | They target autonomous coding agents; we take the pattern, not the dependency (ADR-007) |
| Vector database (Pinecone/Chroma/Qdrant) | We do not do RAG over our own corpus; we search via API + web. Embeddings (if any) locally, without a dedicated database in the minimum plan |
| Postgres/server database **now** | A single-user, local POC with on-prem still distant — SQLite suffices and has no service overhead. Postgres is a **deferred, not rejected** path: it comes with on-prem, without changing models (SQLModel), see §9.4 |
| Cloud model SDKs (Anthropic/Bedrock, etc.) | Breaks on-premise (NFR-M-007) |

---

## 4. Target directory structure
<a id="4-target-directory-structure"></a>

The application structure (an extension of the current POC). Bolded elements already exist in
POC-1.

```
imeto/
├── pyproject.toml              # dependencies, metadata, tools (ruff/mypy/pytest)
├── uv.lock                     # frozen versions (deployment)
├── .env.example                # config template (no secrets)
├── README.md
│
├── imeto/                      # main package
│   ├── __init__.py             # **exists**
│   ├── config.py               # pydantic-settings: all config in one place
│   │
│   ├── core/                   # core shared by the phases
│   │   ├── llm.py              # **exists** — model-agnostic client + retry
│   │   ├── schemas.py          # **exists** — structured-output models (Pydantic)
│   │   ├── provenance.py       # **exists** — Store: source/evidence/claim + audit
│   │   └── span.py             # quote verification/anchoring (from extract.py)
│   │
│   ├── ingest/                 # input layer
│   │   ├── parsing.py          # **exists** — PDF/DOCX -> text with offsets
│   │   └── loaders.py          # metadata anchors: OpenAlex/ORCID/Crossref (MCP)
│   │
│   ├── phases/                 # pipeline PHASES (each = a phase-level harness)
│   │   ├── base.py             # Phase contract + PhaseResult + PhaseContext
│   │   ├── extract.py          # **exists (in imeto/extract.py)** — fact extraction
│   │   ├── suggester.py        # lead suggestions (POC-2)
│   │   ├── argumenter.py       # analysis per FOR/AGAINST/GAP rubric (POC-2)
│   │   ├── writer.py           # editorial assistant + statement map (POC-3)
│   │   └── export.py           # dossier export (POC-3)
│   │
│   ├── orchestration/          # phase orchestrator (linear, human-gated)
│   │   ├── sequencer.py        # phase sequence
│   │   └── gates.py            # gates/approvals (human-in-the-loop)
│   │
│   ├── registries/             # pluggability (harness pattern)
│   │   ├── tools.py            # ToolRegistry (Pydantic I/O, JSON Schema)
│   │   ├── skills.py           # SkillRegistry (.md loaded on demand)
│   │   └── phases.py           # PhaseRegistry
│   │
│   ├── tools/                  # implementations of deterministic tools
│   │   ├── base.py             # Tool contract
│   │   ├── web_search.py       # evidence search (BIP/NGO/media)
│   │   └── metadata.py         # wrapper over ssh_connectors (OpenAlex/Crossref...)
│   │
│   ├── obs/                    # observability/evaluation
│   │   ├── logging.py          # log configuration (decision tracing)
│   │   └── eval.py             # golden-set + core metrics
│   │
│   ├── api/                    # FastAPI (only when a real API/integration is needed)
│   │   ├── app.py              # application assembly
│   │   └── routes/             # endpoints per phase/dossier
│   │
│   ├── ui/                     # Gradio — first GUI (pilot, human gates)
│   │   └── app.py              # thin skin: calls the core, contains NO phase logic
│   │
│   └── cli.py                  # **exists** — CLI (Typer eventually)
│
├── knowledge/                  # LAYER 4 — domain knowledge as data, not code
│   ├── rubryka_kryterium_iii.md
│   ├── typy_dowodow.md
│   └── few_shot/               # examples of good analyses/descriptions (.md)
│
├── data/                       # **exists** — test materials, local databases
│   └── sprawozdanie_test.docx
│
├── docs/                       # **exists**
│   ├── ARCHITEKTURA.md
│   ├── TECHNICZNY.md           # (this document)
│   └── diagramy_podglad.html
│
└── tests/                      # **exists**
    ├── test_span_verification.py
    ├── test_provenance_store.py
    ├── test_phases/            # per-phase tests (with a mocked LLM)
    └── conftest.py             # fixtures (temporary database, LLM stub)
```

**Organizing principle.** The boundary between `core/` (the shared core) and `phases/`
(domain logic) is hard: phases depend on the core, never the reverse. `knowledge/` is **data**
(domain knowledge editable by an expert without touching code) — the realization of layer 4.

---

## 5. Module contracts (interfaces)
<a id="5-module-contracts-interfaces"></a>

The key interfaces on which modularity rests. Illustrative signatures.

### 5.1 Phase

```python
# imeto/phases/base.py
from dataclasses import dataclass
from typing import Protocol

@dataclass
class PhaseContext:
    dossier_id: int
    store: "ProvenanceStore"
    llm: "LLMClient"
    tools: "ToolRegistry"
    skills: "SkillRegistry"

@dataclass
class PhaseResult:
    ok: bool
    summary: str
    produced: list[int]      # ids of records saved in provenance
    needs_human: bool        # whether it requires passing through a gate

class Phase(Protocol):
    name: str
    def run(self, ctx: PhaseContext) -> PhaseResult: ...
```

Each phase is swappable and testable in isolation (mock `llm`, temporary `store`).

### 5.2 Tool

```python
# imeto/tools/base.py
from pydantic import BaseModel

class ToolResult(BaseModel):
    ok: bool
    data: dict
    source_hint: str | None = None   # for creating a source/evidence record

class Tool(Protocol):
    name: str
    description: str
    input_model: type[BaseModel]     # self-describing schema (JSON Schema for the model)
    def execute(self, args: BaseModel) -> ToolResult: ...
```

### 5.3 Skill (domain knowledge)

```python
# imeto/registries/skills.py
class SkillRegistry:
    def load(self, name: str) -> str: ...        # returns the .md content from knowledge/
    def list(self) -> list[str]: ...
```

A skill is a `.md` file loaded into the prompt on a phase's demand — not code, not a constant
in the source.

### 5.4 Provenance (already exists, contract)

```python
# imeto/core/provenance.py  (implemented)
class ProvenanceStore:
    def add_source(self, src: Source) -> int: ...
    def add_evidence(self, ev: Evidence) -> int: ...      # only after span verification
    def evidence_for_source(self, source_id: int) -> list[Row]: ...
    def verify_span(self, source_id: int, ev_id: int) -> bool: ...  # audit (I-audit)
```

---

## 6. Implementation patterns and ideas
<a id="6-implementation-patterns-and-ideas"></a>

### 6.1 Structured output with validation and retry (the anti-hallucination core)

A pattern already implemented in `llm.py`: the model is asked for clean JSON → parsing →
Pydantic validation → on error, append a message and retry. Development ideas:

- **Constrained decoding, if the endpoint supports it.** vLLM and some servers accept
  `response_format={"type":"json_schema", ...}` or GBNF grammars. Enable via a config flag
  (`LLM_JSON_MODE`), treating Pydantic validation as a safety net.
- **Few-shot from `knowledge/few_shot/`.** With a weak model, add 1–2 examples of good output
  to the prompt — this is context engineering (layer 4), not training.

### 6.2 Quote anchoring (level 3 → optionally 2)

- **Level 3 (present):** verbatim matching + tolerance for whitespace only.
- **Level 2 (POC-3, statement map):** when the assistant generates a description sentence, we
  check the semantic coverage of the sentence against an accepted piece of evidence (embedding
  cosine / NLI), with a `match_score` threshold. A low score → the sentence flagged
  "insufficiently grounded", a human decision. Embeddings locally (`sentence-transformers` or
  via the model endpoint), so as not to let data out.

### 6.3 Orchestration as an explicit pipeline

```python
# imeto/orchestration/sequencer.py (sketch)
PIPELINE = [ExtractPhase, SuggesterPhase, ArgumenterPhase, WriterPhase, ExportPhase]

def run_pipeline(ctx: PhaseContext, gate: GateController) -> None:
    for phase_cls in PIPELINE:
        result = phase_cls().run(ctx)
        if result.needs_human:
            gate.await_approval(phase_cls.name, result)   # GATE: the human decides
```

No `while True`. Control stays with the code and the human (Z3, ADR-005).

### 6.4 Idempotency and resumability

- Each phase saves its result to provenance with a `dossier_id` — an interrupted run can be
  resumed from the last completed gate (the dossier state machine — `ARCHITEKTURA.md` §9.4).
- Source import is idempotent by `locator` + content hash (we avoid duplicates).

### 6.5 Determinism where possible

- Low `temperature` (0.0–0.2) for extraction/argumenter (repeatability, fewer hallucinations).
- The suggester may have a higher `temperature` (creativity of leads is desirable, Z1).

---

## 7. Configuration and secrets
<a id="7-configuration-and-secrets"></a>

All configuration in one place, typed (`pydantic-settings`):

```python
# imeto/config.py (sketch)
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "http://localhost:8888/v1"
    llm_api_key: str = "sk-none"
    llm_model: str
    llm_json_mode: bool = False
    llm_temperature: float = 0.2

    db_url: str = "sqlite:///imeto.db"   # changing to postgresql+psycopg://... = engine migration
    knowledge_dir: str = "knowledge"

    crossref_mailto: str | None = None
    openalex_api_key: str | None = None

settings = Settings()  # imported by the rest of the application
```

Principles:
- Secrets **only** from env/.env, never in the code or in the repo (`.env` in `.gitignore`,
  `.env.example` as a template).
- On-prem: secrets injected via the partner's mechanism (container env / secret store).
- `db_url` and `knowledge_dir` configurable — different paths for POC vs deployment; `db_url`
  is at the same time the engine switch (SQLite ↔ Postgres, §9.4).

---

## 8. LLM layer — technical details
<a id="8-llm-layer-technical-details"></a>

- **Interface:** OpenAI Chat Completions (`/v1/chat/completions`). The only touch point with
  the model.
- **Swappability:** changing the model = changing `LLM_BASE_URL`/`LLM_MODEL`. Zero code
  changes.
- **Validation retry:** a parse→validate→(error: append a message)→retry loop, with an attempt
  limit.
- **Network retry:** separate — backoff on 429/5xx/timeout (as in `ssh_connectors/base.py`, a
  shared helper is worthwhile).
- **Streaming:** unnecessary in the POC (we wait for the full JSON). In the UI, consider a
  stream for the editorial (writer) phase, where the user watches the text being produced.
- **Token/cost counting:** on-prem the cost is not monetary, but it is worth logging the
  input/output size (diagnosing slow runs on CPU).
- **Care with a small model:** E2B/4B can be unreliable at verbatim quoting and JSON —
  levers: lower temperature, a harder prompt, constrained decoding, few-shot.

---

## 9. Data layer — technical details
<a id="9-data-layer-technical-details"></a>

### 9.1 Engine and ORM

- **SQLite as the engine**, **SQLModel as the model layer.** The provenance models (`Source`,
  `Evidence`, `Claim`, `ClaimEvidenceLink`, `Dossier`) are defined once as SQLModel classes —
  the same definitions work on SQLite and on Postgres.
- **All access through `ProvenanceStore`** — no other module touches the database/SQL
  directly. This makes the engine swappable: a SQLite→Postgres change touches one layer.
- `PRAGMA foreign_keys=ON` (SQLite enforces foreign keys only once enabled).

### 9.2 Invariants and integrity

- **Invariants** (SAD §8.2) enforced in code, not just in the schema: `add_evidence` accepts a
  record only after span verification; `verify_span` for auditing.
- The anti-hallucination logic is **engine-independent** — it works identically on SQLite and
  Postgres, because it is pure Python over `full_text`/`quote`, not a database function.

### 9.3 Schema migrations in the POC

- In the POC: `SQLModel.metadata.create_all(engine)` — creates missing tables. The schema is
  still evolving (`claim`/`claim_evidence_link`/`dossier` are added in POC-2/3), so Alembic
  would be premature. We introduce it only at the Postgres migration / a stable schema.
- **Export:** the dossier is exportable to JSON with a full provenance trail (provenance as
  the source of truth lets any output format be generated) — also as a way to move data
  between engines.

### 9.4 Postgres migration path
<a id="94-postgres-migration-path"></a>

When on-prem becomes real and you know the partner's environment, migration is cheap,
**provided we keep the discipline from the start**:

**What we do right now (cost ~zero) to make migration cheap:**
- Models in SQLModel (one definition, both engines).
- Access exclusively through `ProvenanceStore` (zero scattered SQL).
- Portable SQL/types — we avoid sqlite-isms (e.g. relying on dynamic typing); `meta` as JSON
  (on Postgres it maps to JSONB).
- Connection string from configuration (`settings.db_url`), not hardcoded.

**What we do at migration time:**
1. Add `psycopg` (v3) and change `db_url` to `postgresql+psycopg://...`.
2. Introduce Alembic; generate a baseline migration from the stable schema.
3. Move the data (JSON export from SQLite → import into Postgres, or an ETL tool).
4. Enable pgvector **only if** the statement map on embeddings comes in (POC-3, level 2) — then
   the embeddings sit in the same database, without a separate vector database.

Estimated cost with the discipline kept: on the order of one working day, without rewriting
logic — the change touches the access and configuration layer, not the core.

---

## 10. Tools and MCP
<a id="10-tools-and-mcp"></a>

Two kinds of tools, both through the shared `Tool` contract:

1. **Metadata anchors** — a wrapper over `ssh_connectors` (OpenAlex/Crossref/CORE/GoTriple)
   via an MCP client. They provide deterministic facts (dates, DOIs, affiliations). Locally
   stdio, on-prem possibly HTTP (a mode already built into `ssh_connectors`).
2. **Impact-evidence search** — `web_search.py`: queries to dispersed sources (BIP, official
   gazettes, NGOs, media). This tool returns **candidates**, not verdicts (Z1); the human
   decides what is evidence.

Every tool result that is to become evidence passes through the same gate as extraction:
creating a `source` (with content/locator) and `evidence` with an anchor. A fact from a tool
is not privileged — it too must have provenance.

---

## 11. Testing and code quality
<a id="11-testing-and-code-quality"></a>

| Layer | Tool | What we test |
|---|---|---|
| Unit | pytest | Span verification, the provenance store, phase contracts |
| LLM/HTTP | pytest + respx | Validation+retry without the network (mocked model responses) |
| Phases | pytest | Each phase with an LLM stub and a temporary database (fixtures in conftest) |
| Lint/format | ruff | Consistent style, catching errors early |
| Types | mypy | Module contracts (Protocol), type safety |

The existing tests (without an LLM) are the template: `test_span_verification.py` simulates the
model's output and checks acceptance/rejection — we test the anti-hallucination logic
independently of the model.

**Principle:** every core module has a test that works **without** a live model. The model is
an external dependency — we mock it, and we measure the model's own quality separately (eval).

---

## 12. Observability and evaluation
<a id="12-observability-and-evaluation"></a>

- **Logging:** stdlib `logging` (POC) → `structlog` when structured logs are needed. We log
  every model call, every gate decision, every fact acceptance/rejection.
- **Decision tracing:** the dossier must be reproducible — a log sufficient to reconstruct why
  a given fact entered/dropped out (NFR-aud).
- **Golden set (from POC-2):** 20–50 pairs (document → expected evidence) in `tests/golden/`.
  Metrics: the share of accepted vs rejected, the number of retries, statement coverage.
- **No external eval services in the minimum plan** (RAGAS/LangSmith are cloud/overhead) — our
  own simple `obs/eval.py` script. Consider one only at scale.

---

## 13. Packaging, running, deployment
<a id="13-packaging-running-deployment"></a>

### 13.1 Packaging

- **`pyproject.toml`** as the single source of truth for dependencies and tools.
- **`uv`** for environment management and locking (`uv sync`, `uv.lock`) — fast, reproducible.
  Alternative: `pip` + `requirements.lock`.

### 13.2 Running (POC)

```bash
uv sync                       # or: python -m venv .venv && pip install -e .
export LLM_BASE_URL=http://localhost:8888/v1
export LLM_API_KEY=sk-...
export LLM_MODEL="<id from /v1/models>"
python -m imeto.cli run data/sprawozdanie_test.docx
```

### 13.3 Deployment (partner's on-prem)

- **Container** (as in `ssh_connectors/Dockerfile`): an image with the application, the model
  separate (vLLM/llama.cpp), connected via `LLM_BASE_URL` in the partner's network.
- **Data:** `provenance.db` on a volume (persistence between runs).
- **Secrets:** the partner's container env / secret store, never in the image.
- **Network:** outbound internet narrow and controlled (metadata anchors, web search), the
  rest closed (SAD §10.3).

---

## 14. Full dependency list
<a id="14-full-dependency-list"></a>

### `pyproject.toml` — dependencies section (proposal)

```toml
[project]
name = "imeto"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.9",
    "pydantic-settings>=2.0",
    "sqlmodel>=0.0.22",
    "openai>=1.30",
    "httpx>=0.27",
    "pdfplumber>=0.11",
    "python-docx>=1.1",
    "typer>=0.12",
]

[project.optional-dependencies]
ui = ["gradio>=4.0"]                          # first GUI (pilot, human gates)
api = ["fastapi>=0.115", "uvicorn>=0.30"]     # only when a real API is needed
mcp = ["mcp>=1.2"]
postgres = ["psycopg>=3.2", "alembic>=1.13"]  # on-prem path (§9.4) — deferred
embed = ["sentence-transformers>=3.0"]        # POC-3, statement map
dev = ["pytest>=8.0", "respx>=0.21", "ruff>=0.6", "mypy>=1.11"]

[project.scripts]
imeto = "imeto.cli:main"
```

Variant installation: `uv sync` (core + SQLite), `uv sync --extra ui` (with the Gradio GUI),
`uv sync --extra mcp` (metadata anchors), `uv sync --extra postgres` (at the on-prem
migration), `uv sync --extra dev` (development).

---

## 15. POC → application migration plan
<a id="15-poc-application-migration-plan"></a>

The refactor order, each step small and testable:

1. **Extract `core/`** — move `llm.py`, `schemas.py`, `provenance.py` into `imeto/core/`,
   pull span verification out of `extract.py` into `core/span.py`. (A clean refactor, tests
   unchanged.)
2. **Rewrite provenance on SQLModel** — `Source`/`Evidence` models as SQLModel classes,
   `ProvenanceStore` on SQLModel sessions; `db_url` from configuration. (Engine still SQLite;
   the provenance tests stay green.)
3. **Introduce the `Phase` contract** — `phases/base.py`, wrap the current extraction as
   `ExtractPhase`.
4. **Add `config.py`** (pydantic-settings) — replace scattered `os.getenv`.
5. **Add the registries** — `tools/`, `skills/`, `phases/` as pluggable.
6. **Build layer 4** — `knowledge/` with the rubric and evidence types; `SkillRegistry`.
7. **Add the thin Gradio GUI** (`ui/app.py`) — human gates (accept/reject candidates); only
   calling the core, zero logic in callbacks.
8. **POC-2: suggester + argumenter** as further phases on the ready skeleton.
9. **POC-3: writer + export** + the statement map (anchoring level 2).
10. **(conditionally) Migration to Postgres** — when on-prem is real: `--extra postgres`,
    Alembic, `db_url` to Postgres (§9.4). Without changing models or the core.
11. **(conditionally) FastAPI API** — when integration/multiple users are needed; this is
    where async enters.

Each step leaves a working system; there is no "big rewrite".

---

*A working document. Library versions current as of June 2026 — before deployment verify the
latest stable ones and freeze them in the lock file.*
