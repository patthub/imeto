# IMeTo — Dokument Techniczny (stack, biblioteki, struktura)

> Uzupełnienie `ARCHITEKTURA.md`. Tamten dokument odpowiada na pytanie **„jak to jest
> poukładane i dlaczego"**; ten odpowiada na **„z czego konkretnie to zbudować"** —
> stack, biblioteki z wersjami i uzasadnieniem, docelowa struktura katalogów, kontrakty
> modułów, konwencje pracy.

| | |
|---|---|
| **Dokument** | Technical Design Document (TDD) |
| **Zakres** | IMeTo — plan minimum (POC-1 → POC-3) |
| **Wersja dok.** | 0.1 (robocza) |
| **Powiązane** | `ARCHITEKTURA.md` (SAD), `IMeTo_Plan_minimum` |
| **Data aktualizacji wersji bibliotek** | czerwiec 2026 |

---

## Spis treści

1. [Założenia i zasady doboru technologii](#1-założenia-i-zasady-doboru-technologii)
2. [Stack technologiczny — przegląd](#2-stack-technologiczny--przegląd)
3. [Biblioteki — wybór, wersje, uzasadnienie](#3-biblioteki--wybór-wersje-uzasadnienie)
4. [Docelowa struktura katalogów](#4-docelowa-struktura-katalogów)
5. [Kontrakty modułów (interfejsy)](#5-kontrakty-modułów-interfejsy)
6. [Wzorce i pomysły implementacyjne](#6-wzorce-i-pomysły-implementacyjne)
7. [Konfiguracja i sekrety](#7-konfiguracja-i-sekrety)
8. [Warstwa LLM — szczegóły techniczne](#8-warstwa-llm--szczegóły-techniczne)
9. [Warstwa danych — szczegóły techniczne](#9-warstwa-danych--szczegóły-techniczne)
10. [Narzędzia (tools) i MCP](#10-narzędzia-tools-i-mcp)
11. [Testy i jakość kodu](#11-testy-i-jakość-kodu)
12. [Obserwowalność i ewaluacja](#12-obserwowalność-i-ewaluacja)
13. [Pakowanie, uruchamianie, wdrożenie](#13-pakowanie-uruchamianie-wdrożenie)
14. [Pełna lista zależności](#14-pełna-lista-zależności)
15. [Plan migracji POC → aplikacja](#15-plan-migracji-poc--aplikacja)

---

## 1. Założenia i zasady doboru technologii

Dobór technologii wynika wprost z zasad architektury i ograniczeń (zob. SAD §2–3):

- **Nudno = dobrze.** Wybieramy biblioteki dojrzałe, szeroko używane, o stabilnym API.
  POC dla jednego użytkownika nie jest miejscem na egzotykę.
- **Minimum zależności.** Każda biblioteka to dług. Domyślnie stdlib; zewnętrzne tylko
  tam, gdzie dają realną wartość (parsowanie, walidacja, klient LLM).
- **Model-agnostyczność (R-swap).** Żadnego SDK zamykającego nas u jednego dostawcy modelu.
- **Bez frameworka agentowego (ADR-005).** Orkiestracja to własny, czytelny kod.
- **On-premise-friendly (NFR-M-007).** Wszystko musi działać bez chmury i bez usług SaaS.
- **Synchronicznie w rdzeniu.** Profil planu minimum (jeden użytkownik, liniowy pipeline,
  jedno wywołanie modelu naraz) nie daje korzyści z async, a async kosztuje czytelność i
  debugowanie. Rdzeń (fazy, provenance, ekstrakcja) jest synchroniczny. Async wprowadzamy
  **tylko** w warstwie API (FastAPI), jeśli i kiedy pojawi się realna równoległość.

---

## 2. Stack technologiczny — przegląd

```
Język          Python 3.12+            (match statements, lepsze typy, wydajność)
Walidacja      Pydantic v2             (egzekwowalny structured output)
Klient LLM     openai SDK (OpenAI-compatible)  + httpx pod spodem
Dane           SQLite via SQLModel      (silnik wymienny na Postgres bez zmiany modeli)
Parsowanie     pdfplumber, python-docx
Współbieżność  SYNCHRONICZNIE w rdzeniu (async tylko w warstwie API, gdy/jeśli zajdzie)
HTTP/narzędzia httpx + MCP (ssh_connectors) dla kotwic metadanych
GUI            Gradio (pierwsze GUI, progi człowieka) → FastAPI gdy potrzeba API
Konfiguracja   pydantic-settings + .env
Testy          pytest                  (+ respx do mockowania HTTP)
Jakość         ruff (lint+format), mypy (typy)
Pakowanie      uv / pip + pyproject.toml
Obserwowalność logging stdlib → opcjonalnie structlog; golden-set eval własny
```

**Trzy decyzje, które warto wyróżnić (ustalone świadomie, nie domyślnie):**

1. **SQLite przez SQLModel, nie goły sqlite3, nie Postgres.** Profil planu minimum to
   jeden użytkownik, lokalnie, on-prem odległy — SQLite jest tu właściwy (zero
   administracji, „uruchom i działa"). „Zapas na przyszłość" daje **architektura, nie
   silnik bazy**: SQLModel definiuje modele raz i działa zarówno na SQLite, jak i na
   Postgresie; cały dostęp idzie przez `ProvenanceStore`. Migracja na Postgres, gdy on-prem
   stanie się realny, to zmiana connection stringa + migracja danych, nie przepisywanie
   (zob. [§9.4 Ścieżka migracji na Postgres](#94-ścieżka-migracji-na-postgres)).
2. **Rdzeń synchroniczny.** Profil obciążenia (jeden użytkownik, liniowy pipeline, jedno
   wywołanie modelu naraz) nie daje korzyści z async, a async kosztuje czytelność i
   debugowanie. Async wprowadzamy **tylko** w warstwie API (FastAPI), jeśli i kiedy pojawi
   się realna równoległość. Rdzeń (fazy, provenance, ekstrakcja) zostaje sync.
3. **Gradio jako pierwsze GUI.** Do pilotażu i realizacji progów człowieka (pokaż
   kandydatów → akceptuj/odrzuć → pipeline rusza) Gradio daje klikalny interfejs za ułamek
   wysiłku pełnego frontendu. FastAPI dokładamy dopiero, gdy potrzeba prawdziwego API/
   integracji. **Reguła nadrzędna:** GUI to cienka skórka wołająca rdzeń — logika nigdy
   w callbackach UI.

Warstwa „w POC → w aplikacji" jest celowa: POC używa najlżejszego wariantu (CLI/Gradio,
SQLite), aplikacja dokłada warstwy (FastAPI, ew. Postgres) bez zmiany rdzenia.

---

## 3. Biblioteki — wybór, wersje, uzasadnienie

> Wersje aktualne na czerwiec 2026. Podajemy dolne granice (`>=`), nie sztywne piny —
> piny trafiają do `uv.lock` / `requirements.lock` przy wdrożeniu.

### 3.1 Rdzeń (wymagane od POC-1)

| Biblioteka | Wersja | Rola | Dlaczego ta |
|---|---|---|---|
| **pydantic** | `>=2.9` | Walidacja structured output, modele danych | Standard de facto; v2 szybka, egzekwuje kontrakt formatu (ADR-003). Aktualnie 2.13.x |
| **openai** | `>=1.30` | Klient OpenAI-compatible (Unsloth/vLLM/partner) | Model-agnostyczność: ten sam kod dla lokalnego i on-prem (ADR-002) |
| **httpx** | `>=0.27` | Transport HTTP (pod openai + własne narzędzia) | Async, nowoczesny; ciągnięty i tak przez openai SDK |
| **pdfplumber** | `>=0.11` | Parsowanie PDF z zachowaniem treści | Dobre wydobycie tekstu/układu; kluczowe dla dosłowności cytatów (ADR-004) |
| **python-docx** | `>=1.1` | Parsowanie/Generowanie DOCX | Standard dla .docx; używany też do dokumentu testowego |
| **sqlmodel** | `>=0.0.22` | ORM nad SQLite (silnik wymienny na Postgres) | Pydantic + SQLAlchemy w jednym; modele danych = modele walidacji. Definicja raz → SQLite i Postgres |
| **pydantic-settings** | `>=2.0` | Konfiguracja z env/.env | Spójna z Pydantic; typowana konfiguracja zamiast `os.getenv` rozsianego po kodzie |

> **Uwaga o httpx.** W 2026 Pydantic Services przejęło opiekę nad httpx, publikując je
> także jako pakiet `httpx2` (import `httpx2`) z gwarancją utrzymania i aktualizacji
> bezpieczeństwa. API jest zgodne. **Rekomendacja:** zostań przy `httpx` (mniejsze ryzyko,
> ciągnięty przez openai SDK); rozważ `httpx2` tylko jeśli zależy Ci na najświeższych
> łatkach bezpieczeństwa i kontrolujesz cały graf zależności.

### 3.2 Aplikacja (od momentu, gdy CLI przestaje wystarczać)

| Biblioteka | Wersja | Rola | Dlaczego ta |
|---|---|---|---|
| **gradio** | `>=4.0` | Pierwsze GUI: pilotaż + progi człowieka | Klikalny interfejs (akceptuj/odrzuć kandydatów) za ułamek wysiłku frontendu; idealny do human-in-the-loop |
| **typer** | `>=0.12` | CLI (operacje, testy, automatyzacja) | Buduje CLI z type hints; mniej boilerplate niż argparse; spójne z Pydantic |
| **fastapi** | `>=0.115` | API HTTP — dopiero gdy potrzeba integracji | Dojrzałe, async, auto-schema z Pydantic. Aktualnie 0.136.x (Starlette 1.0). Tu wchodzi async |
| **uvicorn** | `>=0.30` | Serwer ASGI dla FastAPI | Standardowy runtime FastAPI |
| **mcp** | `>=1.2` | Klient MCP do `ssh_connectors` (kotwice metadanych) | Spójność z już zbudowanymi konektorami |

### 3.3 Opcjonalne / przyszłościowe (nie wprowadzać przedwcześnie)

| Biblioteka | Kiedy | Po co |
|---|---|---|
| **psycopg** (v3) | gdy on-prem → migracja na Postgres | Sterownik Postgresa (sync i async); SQLModel działa na nim bez zmiany modeli |
| **alembic** | przy migracji na Postgres / stabilnym schemacie | Wersjonowanie migracji bazy (w SQLite POC: `create_all` wystarcza) |
| **sentence-transformers** | przy mapie twierdzeń (POC-3, poziom 2) | Embeddingi do pokrycia semantycznego zdanie↔dowód (lokalnie) |
| **rapidfuzz** | jeśli kotwiczenie wymaga rozmytego dopasowania | Szybkie dopasowanie tekstu; ostrożnie, by nie wpuścić semantyki |
| **structlog** | gdy logi stdlib przestają wystarczać | Strukturalne logowanie (tracing decyzji) |
| **respx** | testy warstwy LLM/HTTP | Mockowanie httpx bez sieci |

### 3.4 Czego ŚWIADOMIE NIE używamy (i dlaczego)

| Odrzucone | Powód |
|---|---|
| LangChain / LangGraph / LlamaIndex | Framework agentowy/RAG — sprzeczny z liniowym, human-gated przepływem (ADR-005). Rozważyć dopiero przy iteracyjnym argumenterze |
| OpenHarness i pokrewne harnessy | Celują w autonomicznych agentów kodujących; bierzemy wzorzec, nie zależność (ADR-007) |
| Wektorowa baza (Pinecone/Chroma/Qdrant) | Nie robimy RAG nad własnym korpusem; szukamy przez API + web. Embeddingi (jeśli) lokalnie, bez dedykowanej bazy w planie minimum |
| Postgres/serwerowa baza **teraz** | POC jednoosobowy, lokalny, on-prem odległy — SQLite wystarcza i nie ma narzutu usługi. Postgres to ścieżka **odłożona, nie odrzucona**: wejdzie przy on-prem, bez zmiany modeli (SQLModel), zob. §9.4 |
| Chmurowe SDK modeli (Anthropic/Bedrock itp.) | Łamie on-premise (NFR-M-007) |

---

## 4. Docelowa struktura katalogów

Struktura aplikacji (rozszerzenie obecnego POC). Pogrubione elementy istnieją już w POC-1.

```
imeto/
├── pyproject.toml              # zależności, metadane, narzędzia (ruff/mypy/pytest)
├── uv.lock                     # zamrożone wersje (wdrożenie)
├── .env.example                # wzór konfiguracji (bez sekretów)
├── README.md
│
├── imeto/                      # pakiet główny
│   ├── __init__.py             # **istnieje**
│   ├── config.py               # pydantic-settings: cała konfiguracja w jednym miejscu
│   │
│   ├── core/                   # rdzeń współdzielony przez fazy
│   │   ├── llm.py              # **istnieje** — klient model-agnostyczny + retry
│   │   ├── schemas.py          # **istnieje** — modele structured output (Pydantic)
│   │   ├── provenance.py       # **istnieje** — Store: source/evidence/claim + audyt
│   │   └── span.py             # weryfikacja/kotwiczenie cytatów (z extract.py)
│   │
│   ├── ingest/                 # warstwa wejścia
│   │   ├── parsing.py          # **istnieje** — PDF/DOCX -> tekst z offsetami
│   │   └── loaders.py          # kotwice metadanych: OpenAlex/ORCID/Crossref (MCP)
│   │
│   ├── phases/                 # FAZY pipeline'u (każda = harness na poziomie fazy)
│   │   ├── base.py             # kontrakt Phase + PhaseResult + PhaseContext
│   │   ├── extract.py          # **istnieje (w imeto/extract.py)** — ekstrakcja faktów
│   │   ├── suggester.py        # propozycje tropów (POC-2)
│   │   ├── argumenter.py       # rozbiór wg rubryki ZA/PRZECIW/LUKI (POC-2)
│   │   ├── writer.py           # asystent redakcyjny + mapa twierdzeń (POC-3)
│   │   └── export.py           # eksport dossier (POC-3)
│   │
│   ├── orchestration/          # orkiestrator faz (liniowy, human-gated)
│   │   ├── sequencer.py        # sekwencja faz
│   │   └── gates.py            # progi/zatwierdzenia (human-in-the-loop)
│   │
│   ├── registries/             # pluginowalność (wzorzec harness)
│   │   ├── tools.py            # ToolRegistry (Pydantic I/O, JSON Schema)
│   │   ├── skills.py           # SkillRegistry (.md ładowane na żądanie)
│   │   └── phases.py           # PhaseRegistry
│   │
│   ├── tools/                  # implementacje narzędzi deterministycznych
│   │   ├── base.py             # kontrakt Tool
│   │   ├── web_search.py       # wyszukiwanie dowodów (BIP/NGO/media)
│   │   └── metadata.py         # owijka na ssh_connectors (OpenAlex/Crossref...)
│   │
│   ├── obs/                    # obserwowalność/ewaluacja
│   │   ├── logging.py          # konfiguracja logów (tracing decyzji)
│   │   └── eval.py             # golden-set + metryki rdzenia
│   │
│   ├── api/                    # FastAPI (dopiero gdy potrzeba prawdziwego API/integracji)
│   │   ├── app.py              # montaż aplikacji
│   │   └── routes/             # endpointy per faza/dossier
│   │
│   ├── ui/                     # Gradio — pierwsze GUI (pilotaż, progi człowieka)
│   │   └── app.py              # cienka skórka: woła rdzeń, NIE zawiera logiki faz
│   │
│   └── cli.py                  # **istnieje** — CLI (Typer docelowo)
│
├── knowledge/                  # WARSTWA 4 — wiedza dziedzinowa jako dane, nie kod
│   ├── rubryka_kryterium_iii.md
│   ├── typy_dowodow.md
│   └── few_shot/               # przykłady dobrych rozbiorów/opisów (.md)
│
├── data/                       # **istnieje** — materiały testowe, lokalne bazy
│   └── sprawozdanie_test.docx
│
├── docs/                       # **istnieje**
│   ├── ARCHITEKTURA.md
│   ├── TECHNICZNY.md           # (ten dokument)
│   └── diagramy_podglad.html
│
└── tests/                      # **istnieje**
    ├── test_span_verification.py
    ├── test_provenance_store.py
    ├── test_phases/            # testy per faza (z mockiem LLM)
    └── conftest.py             # fixtury (tymczasowa baza, atrapa LLM)
```

**Zasada organizacji.** Granica `core/` (współdzielony rdzeń) vs `phases/` (logika
domenowa) jest twarda: fazy zależą od rdzenia, nigdy odwrotnie. `knowledge/` to **dane**
(wiedza dziedzinowa edytowalna przez eksperta bez dotykania kodu) — realizacja warstwy 4.

---

## 5. Kontrakty modułów (interfejsy)

Kluczowe interfejsy, na których opiera się modularność. Sygnatury poglądowe.

### 5.1 Faza (Phase)

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
    produced: list[int]      # id rekordów zapisanych w provenance
    needs_human: bool        # czy wymaga przejścia przez próg

class Phase(Protocol):
    name: str
    def run(self, ctx: PhaseContext) -> PhaseResult: ...
```

Każda faza jest wymienna i testowalna w izolacji (mock `llm`, tymczasowy `store`).

### 5.2 Narzędzie (Tool)

```python
# imeto/tools/base.py
from pydantic import BaseModel

class ToolResult(BaseModel):
    ok: bool
    data: dict
    source_hint: str | None = None   # do utworzenia rekordu source/evidence

class Tool(Protocol):
    name: str
    description: str
    input_model: type[BaseModel]     # samoopisowy schemat (JSON Schema dla modelu)
    def execute(self, args: BaseModel) -> ToolResult: ...
```

### 5.3 Skill (wiedza dziedzinowa)

```python
# imeto/registries/skills.py
class SkillRegistry:
    def load(self, name: str) -> str: ...        # zwraca treść .md z knowledge/
    def list(self) -> list[str]: ...
```

Skill to plik `.md` ładowany do promptu na żądanie fazy — nie kod, nie stała w źródle.

### 5.4 Provenance (już istnieje, kontrakt)

```python
# imeto/core/provenance.py  (zaimplementowane)
class ProvenanceStore:
    def add_source(self, src: Source) -> int: ...
    def add_evidence(self, ev: Evidence) -> int: ...      # tylko po weryfikacji spanu
    def evidence_for_source(self, source_id: int) -> list[Row]: ...
    def verify_span(self, source_id: int, ev_id: int) -> bool: ...  # audyt (I-audit)
```

---

## 6. Wzorce i pomysły implementacyjne

### 6.1 Structured output z walidacją i retry (rdzeń anty-halucynacji)

Wzorzec już zaimplementowany w `llm.py`: model proszony o czysty JSON → parsowanie →
walidacja Pydantic → przy błędzie doklejenie komunikatu i retry. Pomysły rozwojowe:

- **Constrained decoding, jeśli endpoint wspiera.** vLLM i część serwerów akceptują
  `response_format={"type":"json_schema", ...}` lub gramatyki GBNF. Włączać przez flagę
  konfiguracji (`LLM_JSON_MODE`), traktując walidację Pydantic jako siatkę bezpieczeństwa.
- **Few-shot z `knowledge/few_shot/`.** Przy słabym modelu dołożyć 1–2 przykłady dobrego
  wyjścia do promptu — to context engineering (warstwa 4), nie trening.

### 6.2 Kotwiczenie cytatów (poziom 3 → opcjonalnie 2)

- **Poziom 3 (jest):** dosłowne dopasowanie + tolerancja wyłącznie na białe znaki.
- **Poziom 2 (POC-3, mapa twierdzeń):** gdy asystent generuje zdanie opisu, sprawdzamy
  pokrycie semantyczne zdania z zaakceptowanym dowodem (embedding cosine / NLI), z progiem
  `match_score`. Niski score → zdanie oznaczone „bez wystarczającego oparcia", decyzja
  człowieka. Embeddingi lokalnie (`sentence-transformers` lub przez endpoint modelu), by
  nie wypuszczać danych.

### 6.3 Orkiestracja jako jawny pipeline

```python
# imeto/orchestration/sequencer.py (szkic)
PIPELINE = [ExtractPhase, SuggesterPhase, ArgumenterPhase, WriterPhase, ExportPhase]

def run_pipeline(ctx: PhaseContext, gate: GateController) -> None:
    for phase_cls in PIPELINE:
        result = phase_cls().run(ctx)
        if result.needs_human:
            gate.await_approval(phase_cls.name, result)   # PRÓG: człowiek decyduje
```

Brak `while True`. Sterowanie u kodu i człowieka (Z3, ADR-005).

### 6.4 Idempotencja i wznawialność

- Każda faza zapisuje wynik do provenance z `dossier_id` — przerwany przebieg da się
  wznowić od ostatniego ukończonego progu (maszyna stanów dossier — `ARCHITEKTURA.md` §9.4).
- Import źródła jest idempotentny po `locator` + hash treści (unikamy duplikatów).

### 6.5 Determinizm tam, gdzie to możliwe

- `temperature` niska (0.0–0.2) dla ekstrakcji/argumentera (powtarzalność, mniej halucynacji).
- Suggester może mieć wyższą `temperature` (kreatywność tropów jest pożądana, Z1).

---

## 7. Konfiguracja i sekrety

Cała konfiguracja w jednym miejscu, typowana (`pydantic-settings`):

```python
# imeto/config.py (szkic)
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "http://localhost:8888/v1"
    llm_api_key: str = "sk-none"
    llm_model: str
    llm_json_mode: bool = False
    llm_temperature: float = 0.2

    db_url: str = "sqlite:///imeto.db"   # zmiana na postgresql+psycopg://... = migracja silnika
    knowledge_dir: str = "knowledge"

    crossref_mailto: str | None = None
    openalex_api_key: str | None = None

settings = Settings()  # importowane przez resztę aplikacji
```

Zasady:
- Sekrety **wyłącznie** z env/.env, nigdy w kodzie ani w repo (`.env` w `.gitignore`,
  `.env.example` jako wzór).
- Na on-prem: sekrety wstrzykiwane przez mechanizm partnera (env kontenera / secret store).
- `db_url` i `knowledge_dir` konfigurowalne — różne ścieżki POC vs wdrożenie; `db_url` to
  jednocześnie przełącznik silnika (SQLite ↔ Postgres, §9.4).

---

## 8. Warstwa LLM — szczegóły techniczne

- **Interfejs:** OpenAI Chat Completions (`/v1/chat/completions`). Jedyny punkt styku z modelem.
- **Wymienność:** zmiana modelu = zmiana `LLM_BASE_URL`/`LLM_MODEL`. Zero zmian w kodzie.
- **Retry walidacji:** pętla parse→validate→(błąd: dolep komunikat)→retry, limit prób.
- **Retry sieciowy:** osobno — backoff na 429/5xx/timeout (jak w `ssh_connectors/base.py`,
  warto wspólny helper).
- **Strumieniowanie:** w POC niepotrzebne (czekamy na pełny JSON). W UI rozważyć stream dla
  fazy redakcyjnej (writer), gdzie użytkownik widzi powstający tekst.
- **Liczenie tokenów/kosztu:** na on-prem koszt nie jest pieniężny, ale warto logować
  rozmiar wejścia/wyjścia (diagnoza wolnych przebiegów na CPU).
- **Ostrożność z małym modelem:** E2B/4B bywa zawodny w dosłownym cytowaniu i JSON —
  dźwignie: niższa temperatura, twardszy prompt, constrained decoding, few-shot.

---

## 9. Warstwa danych — szczegóły techniczne

### 9.1 Silnik i ORM

- **SQLite jako silnik**, **SQLModel jako warstwa modeli.** Modele provenance (`Source`,
  `Evidence`, `Claim`, `ClaimEvidenceLink`, `Dossier`) zdefiniowane raz jako klasy
  SQLModel — te same definicje działają na SQLite i na Postgresie.
- **Cały dostęp przez `ProvenanceStore`** — żaden inny moduł nie dotyka bazy/SQL
  bezpośrednio. To czyni silnik wymiennym: zmiana SQLite→Postgres dotyka jednej warstwy.
- `PRAGMA foreign_keys=ON` (SQLite egzekwuje klucze obce dopiero po włączeniu).

### 9.2 Niezmienniki i integralność

- **Niezmienniki** (SAD §8.2) egzekwowane w kodzie, nie tylko w schemacie:
  `add_evidence` przyjmuje rekord dopiero po weryfikacji spanu; `verify_span` do audytu.
- Logika anty-halucynacji jest **niezależna od silnika** — działa identycznie na SQLite
  i Postgresie, bo to czysty Python nad `full_text`/`quote`, nie funkcja bazy.

### 9.3 Migracje schematu w POC

- W POC: `SQLModel.metadata.create_all(engine)` — tworzy brakujące tabele. Schemat wciąż
  ewoluuje (dochodzą `claim`/`claim_evidence_link`/`dossier` w POC-2/3), więc Alembic
  byłby przedwczesny. Wprowadzamy go dopiero przy migracji na Postgres / stabilnym schemacie.
- **Eksport:** dossier eksportowalne do JSON z pełnym śladem pochodzenia (provenance jako
  źródło prawdy pozwala wygenerować dowolny format wyjścia) — także jako droga przeniesienia
  danych między silnikami.

### 9.4 Ścieżka migracji na Postgres

Gdy on-prem stanie się realny i poznasz środowisko partnera, migracja jest tania, **o ile
trzymamy dyscyplinę od początku**:

**Co robimy już teraz (koszt ~zero), by migracja była tania:**
- Modele w SQLModel (jedna definicja, oba silniki).
- Dostęp wyłącznie przez `ProvenanceStore` (zero rozsianego SQL).
- SQL/typy przenośne — unikamy sqlite-izmów (np. polegania na dynamicznym typowaniu);
  `meta` jako JSON (na Postgresie zmapuje się na JSONB).
- Connection string z konfiguracji (`settings.db_url`), nie zaszyty.

**Co robimy w momencie migracji:**
1. Dodaj `psycopg` (v3) i zmień `db_url` na `postgresql+psycopg://...`.
2. Wprowadź Alembic; wygeneruj migrację bazową ze stabilnego schematu.
3. Przenieś dane (eksport JSON z SQLite → import do Postgresa, albo narzędziem ETL).
4. Włącz pgvector **tylko jeśli** wchodzi mapa twierdzeń na embeddingach (POC-3, poziom 2) —
   wtedy embeddingi siedzą w tej samej bazie, bez osobnej bazy wektorowej.

Szacunkowy koszt przy zachowanej dyscyplinie: rzędu jednego dnia roboczego, bez
przepisywania logiki — zmiana dotyka warstwy dostępu i konfiguracji, nie rdzenia.

---

## 10. Narzędzia (tools) i MCP

Dwa rodzaje narzędzi, oba przez wspólny kontrakt `Tool`:

1. **Kotwice metadanych** — owijka na `ssh_connectors` (OpenAlex/Crossref/CORE/GoTriple)
   przez klienta MCP. Dostarczają deterministycznych faktów (daty, DOI, afiliacje).
   Lokalnie stdio, na on-prem ewentualnie HTTP (tryb już wbudowany w `ssh_connectors`).
2. **Wyszukiwanie dowodów wpływu** — `web_search.py`: zapytania do źródeł rozproszonych
   (BIP, dzienniki urzędowe, NGO, media). To narzędzie zwraca **kandydatów**, nie werdykty
   (Z1); człowiek decyduje, co jest dowodem.

Każdy wynik narzędzia, który ma stać się dowodem, przechodzi przez tę samą bramkę co
ekstrakcja: utworzenie `source` (z treścią/locatorem) i `evidence` z kotwicą. Fakt z
narzędzia nie jest uprzywilejowany — też musi mieć pochodzenie.

---

## 11. Testy i jakość kodu

| Warstwa | Narzędzie | Co testujemy |
|---|---|---|
| Jednostkowe | pytest | Weryfikacja spanu, provenance store, kontrakty faz |
| LLM/HTTP | pytest + respx | Walidacja+retry bez sieci (mock odpowiedzi modelu) |
| Fazy | pytest | Każda faza z atrapą LLM i tymczasową bazą (fixtury w conftest) |
| Lint/format | ruff | Spójny styl, wczesne wyłapanie błędów |
| Typy | mypy | Kontrakty modułów (Protocol), bezpieczeństwo typów |

Istniejące testy (bez LLM) są wzorem: `test_span_verification.py` symuluje wyjście modelu
i sprawdza akceptację/odrzucenie — testujemy logikę anty-halucynacji niezależnie od modelu.

**Zasada:** każdy moduł rdzenia ma test, który działa **bez** żywego modelu. Model to
zależność zewnętrzna — mockujemy ją, a jakość samego modelu mierzymy osobno (eval).

---

## 12. Obserwowalność i ewaluacja

- **Logowanie:** stdlib `logging` (POC) → `structlog` gdy potrzeba logów strukturalnych.
  Logujemy każde wywołanie modelu, decyzję progu, akcepty/odrzucenia faktów.
- **Tracing decyzji:** dossier musi być odtwarzalne — log wystarczający, by zrekonstruować,
  dlaczego dany fakt wszedł/wypadł (NFR-aud).
- **Golden set (od POC-2):** 20–50 par (dokument → oczekiwane dowody) w `tests/golden/`.
  Metryki: odsetek zaakceptowanych vs odrzuconych, liczba retry, pokrycie twierdzeń.
- **Bez zewnętrznych usług eval w planie minimum** (RAGAS/LangSmith to chmura/overhead) —
  własny, prosty skrypt `obs/eval.py`. Rozważyć dopiero przy skali.

---

## 13. Pakowanie, uruchamianie, wdrożenie

### 13.1 Pakowanie

- **`pyproject.toml`** jako jedyne źródło prawdy o zależnościach i narzędziach.
- **`uv`** do zarządzania środowiskiem i lockowania (`uv sync`, `uv.lock`) — szybkie,
  reprodukowalne. Alternatywa: `pip` + `requirements.lock`.

### 13.2 Uruchamianie (POC)

```bash
uv sync                       # lub: python -m venv .venv && pip install -e .
export LLM_BASE_URL=http://localhost:8888/v1
export LLM_API_KEY=sk-...
export LLM_MODEL="<id z /v1/models>"
python -m imeto.cli run data/sprawozdanie_test.docx
```

### 13.3 Wdrożenie (on-prem partnera)

- **Kontener** (jak w `ssh_connectors/Dockerfile`): obraz z aplikacją, model osobno
  (vLLM/llama.cpp), połączenie przez `LLM_BASE_URL` w sieci partnera.
- **Dane:** `provenance.db` na wolumenie (trwałość między uruchomieniami).
- **Sekrety:** env kontenera / secret store partnera, nigdy w obrazie.
- **Sieć:** wyjście do internetu wąskie i sterowane (kotwice metadanych, web search),
  reszta zamknięta (SAD §10.3).

---

## 14. Pełna lista zależności

### `pyproject.toml` — sekcja zależności (propozycja)

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
ui = ["gradio>=4.0"]                          # pierwsze GUI (pilotaż, progi człowieka)
api = ["fastapi>=0.115", "uvicorn>=0.30"]     # dopiero gdy potrzeba prawdziwego API
mcp = ["mcp>=1.2"]
postgres = ["psycopg>=3.2", "alembic>=1.13"]  # ścieżka on-prem (§9.4) — odłożona
embed = ["sentence-transformers>=3.0"]        # POC-3, mapa twierdzeń
dev = ["pytest>=8.0", "respx>=0.21", "ruff>=0.6", "mypy>=1.11"]

[project.scripts]
imeto = "imeto.cli:main"
```

Instalacja wariantowa: `uv sync` (rdzeń + SQLite), `uv sync --extra ui` (z GUI Gradio),
`uv sync --extra mcp` (kotwice metadanych), `uv sync --extra postgres` (przy migracji on-prem),
`uv sync --extra dev` (rozwój).

---

## 15. Plan migracji POC → aplikacja

Kolejność refaktoru, każdy krok mały i testowalny:

1. **Wydzielić `core/`** — przenieść `llm.py`, `schemas.py`, `provenance.py` do `imeto/core/`,
   wyciągnąć weryfikację spanu z `extract.py` do `core/span.py`. (Czysty refaktor, testy bez zmian.)
2. **Przepisać provenance na SQLModel** — modele `Source`/`Evidence` jako klasy SQLModel,
   `ProvenanceStore` na sesjach SQLModel; `db_url` z konfiguracji. (Silnik nadal SQLite;
   testy provenance pozostają zielone.)
3. **Wprowadzić kontrakt `Phase`** — `phases/base.py`, opakować obecną ekstrakcję jako `ExtractPhase`.
4. **Dodać `config.py`** (pydantic-settings) — zastąpić rozsiane `os.getenv`.
5. **Dodać rejestry** — `tools/`, `skills/`, `phases/` jako pluginowalne.
6. **Zbudować warstwę 4** — `knowledge/` z rubryką i typami dowodów; `SkillRegistry`.
7. **Dodać cienkie GUI Gradio** (`ui/app.py`) — progi człowieka (akceptuj/odrzuć kandydatów);
   wyłącznie wołanie rdzenia, zero logiki w callbackach.
8. **POC-2: suggester + argumenter** jako kolejne fazy na gotowym szkielecie.
9. **POC-3: writer + export** + mapa twierdzeń (poziom 2 kotwiczenia).
10. **(warunkowo) Migracja na Postgres** — gdy on-prem realny: `--extra postgres`, Alembic,
    `db_url` na Postgresa (§9.4). Bez zmiany modeli ani rdzenia.
11. **(warunkowo) API FastAPI** — gdy potrzeba integracji/wielu użytkowników; tu wchodzi async.

Każdy krok zostawia działający system; nie ma „wielkiego przepisania".

---

*Dokument roboczy. Wersje bibliotek aktualne na czerwiec 2026 — przed wdrożeniem zweryfikuj
najnowsze stabilne i zamroź w pliku lock.*
