# IMeTo — Project Documentation

> This document describes **what we have already built, how it works, and why it works
> that way**. It is written so that a less technical reader can follow it too — technical
> terms are explained on first use, and there is a [glossary](#slownik-pojec) at the end.
>
> Related documents: `TECHNICZNY.md` (the detailed technical plan) and `CLAUDE.md`
> (instructions for the AI assistant working on the code).

---

## Table of contents

1. [What IMeTo is for (in one paragraph)](#1-po-co-jest-imeto)
2. [The core idea: a quote must be grounded](#2-glowna-idea-cytat-musi-miec-pokrycie)
3. [How the system is conceived as a whole](#3-jak-system-jest-pomyslany-jako-calosc)
4. [What we have already built — module by module](#4-co-juz-zbudowalismy)
5. [How facts are extracted, step by step](#5-jak-wyciagane-sa-fakty)
6. [Data model and standards compliance](#6-model-danych-i-zgodnosc-ze-standardami)
7. [How to run and check it yourself](#7-jak-to-uruchomic-i-sprawdzic)
8. [What comes next on the roadmap](#8-co-jest-dalej-w-planie)
9. [Glossary](#slownik-pojec)

---

## 1. What IMeTo is for
<a id="1-po-co-jest-imeto"></a>

IMeTo is a tool that **reads documents** (e.g. reports, publications in PDF or Word
format) and **fishes facts out of them**, where every fact must be **backed by a verbatim
quote** from the source. Ultimately it helps a person assess the output or impact
described in the documents — but it does so in a way that **invents nothing**: every
sentence the system produces can be traced back to a specific place in the original
document.

The key constraints that shape the whole project:

- **Single user, local.** This is not a cloud service for thousands of people. It is meant
  to run on a single computer ("on-premise", i.e. on your own machine, without sending data
  outside).
- **The human decides.** The system proposes candidate facts; it is the human who accepts
  or rejects them. The system never "pushes through" conclusions on its own.
- **Minimal dependencies, boring technologies.** The less exotic the stack, the fewer things
  break.

---

## 2. The core idea: a quote must be grounded
<a id="2-glowna-idea-cytat-musi-miec-pokrycie"></a>

The biggest risk when using language models (AI of the ChatGPT variety) is
**hallucination** — the model can write a sentence that sounds credible but is made up or
distorted. In assessing scholarly output that would be catastrophic.

IMeTo solves this with one iron rule:

> **No fact enters the store until its quote has been found *verbatim* in the source
> text.**

In practice this works as follows: the model points to a fragment of the document as
evidence (e.g. "The municipal council adopted resolution no. 12"). Before IMeTo records it,
it **checks character by character** whether that fragment really occurs in the original.
If the model distorted even a single digit ("no. 13" instead of "no. 12"), the fact is
**rejected**. We tolerate only differences in so-called whitespace (spaces, line breaks),
because the model often "collapses" text — but the content must match to the character.

This verification is the heart of the system. Everything else is built around it.

---

## 3. How the system is conceived as a whole
<a id="3-jak-system-jest-pomyslany-jako-calosc"></a>

Ultimately IMeTo is a **pipeline** — a sequence of stages a document passes through:

```
document  →  [fact extraction]  →  [lead suggestions]  →  [FOR/AGAINST analysis]
          →  [editorial assistant]  →  [dossier export]
```

After each stage there can be a **gate** — a moment where the system stops and waits for a
human decision (accept / reject) before moving on.

**Important:** as of today we have built the foundations and the first stage (extraction).
The later stages (lead suggestions, analysis, editing, export) are planned but do not yet
exist. This document describes **the actual state**, not the plans.

The architecture splits the code into two layers with a hard boundary between them:

- **Core (`core/`)** — shared, general building blocks: quote verification, the data
  contract, the database, the AI client. The core knows nothing about the specific domain
  (assessing scholarly output).
- **Phases (`phases/`)** — the logic of the individual pipeline stages. Phases use the core,
  **never the other way around**. This keeps the core stable while stages can be swapped
  out.

---

## 4. What we have already built
<a id="4-co-juz-zbudowalismy"></a>

We build step by step. Each step leaves behind a **working, tested** system — there is no
moment where "nothing works because we're rewriting everything". Below is each element
built: first in plain language, then a technical note.

### Step 0 — Project skeleton (scaffolding)

**Plainly:** before any actual code existed, we prepared the "workshop" — files that state
what the project consists of, which tools it uses, and how to check that everything holds
together. It computes nothing on its own, but without it you cannot work.

**Technically:**
- `pyproject.toml` — a single place listing dependencies (libraries) and the configuration
  of code-quality tools.
- `.gitignore` — a list of things we do not commit to the project history (among others,
  secrets and the local database).
- `.env.example` — a template settings file (without real passwords).
- `imeto/__init__.py` — the main package, empty for now.
- `tests/test_smoke.py` — the simplest possible test: "does the project even load".

### Step 1 — Quote verification (`imeto/core/span.py`)

**Plainly:** a function that answers a single question: *"does this quote really occur in
this document, verbatim?"*. If so, it says exactly where (from which character to which). If
not, it says "no". This is the iron rule from point 2, turned into code.

**Technically:** the `find_span(full_text, quote)` function returns a pair of numbers
`(start, end)` — the position of the quote in the text — or `None`. Non-whitespace
characters must match to the character (letter case, digits, punctuation). Runs of
whitespace in the quote match any whitespace in the source, so the returned position points
to the **original**, even if the model collapsed spaces or line breaks. This corresponds to
"level 3" anchoring from the technical plan. Zero AI, zero database — pure, predictable
logic, fully testable.

### Step 2 — The model's response contract (`imeto/core/schemas.py`)

**Plainly:** deciding the *exact* form in which the AI model must return results. It is like
a form with fields: the model must fill in exactly those fields and no others. If it tries
to add anything of its own, the response is rejected.

**Technically:** the data models `ExtractedFact` (a single fact: `quote` — the verbatim
quote, and `statement` — the content of the fact that the quote supports) and `Extraction`
(a list of facts). Built on the Pydantic library, with the setting "forbid extra fields"
(`extra="forbid"`) and the requirement that texts must not be empty. Design note: the model
does **not** provide the quote's position in the text — we compute the position ourselves
(step 1), because we do not trust the model on that.

### Step 3 — The provenance database (`imeto/core/provenance.py`)

**Plainly:** this is the "archive with pedigrees". It stores sources (documents) and
evidence (verified quotes), but crucially — **when saving a piece of evidence it re-checks
the quote**. You cannot slip into the archive something that is not grounded in the source.
Additionally, for each piece of evidence it records a "pedigree": when it was created, which
process produced it, and which AI model is responsible for it — so that it is always
possible to reconstruct where a given fact came from.

**Technically:** two tables — `Source` (a document) and `Evidence` (a verified quote) —
built on the SQLModel library over a SQLite database (a lightweight single-file database
with no server). All database access goes through the `ProvenanceStore` class — no other
module touches the database directly, so in the future the engine can be swapped (for
Postgres) without rewriting the rest. The `add_evidence` method enforces the invariant: it
calls `find_span` from step 1 and either saves the evidence with computed positions or
raises a `SpanNotVerified` error. Column names and types conform to international standards
for describing data — more on this in [chapter 6](#6-model-danych-i-zgodnosc-ze-standardami).

### Step 4 — Settings (`imeto/config.py`)

**Plainly:** a single place for all program settings — the AI model's address, the model
name, the database path, and so on. Instead of scattering these values across the code, we
keep them in one place and load them from a settings file. Passwords and keys are **never**
in the code.

**Technically:** the `Settings` class built on the pydantic-settings library, loading values
from a `.env` file or environment variables, with typing (e.g. numbers are numbers, and
true/false are boolean values). The `db_url` field is at the same time the database engine
switch (SQLite ↔ Postgres).

### Step 5 — The AI model client (`imeto/core/llm.py`)

**Plainly:** this is the "translator" between IMeTo and the AI model. It sends the model an
instruction, receives the response, and **makes sure the response has the right form**. If
the model replies with a mess instead of a filled-in form, the client shows it the error and
asks for a correction, and does so a few times until it gets something valid (or gives up and
raises an error). It is "model-agnostic", i.e. indifferent to which model is underneath — you
can swap it by changing only the address and name, without touching the code.

**Technically:** the `LLMClient` class uses the `openai` library (the standard for
communicating with OpenAI-API-compatible models — it also handles local models). The
`structured` method runs a loop: call the model → parse and validate the response against the
schema from step 2 → on a mismatch, append the error message and retry, up to a limit.
Network retries (when the server temporarily fails to respond) are handled by the SDK itself
— we do not duplicate that. The client is tested **without connecting to the network**: in
tests we substitute a stub response (the respx library), which lets us check our logic
independently of whether any model happens to be up.

### Step 6 — Loading documents (`imeto/ingest/parsing.py`)

**Plainly:** a function that takes a PDF or Word file and turns it into plain text you can
work with further (e.g. search for quotes). If someone passes a file in an unsupported
format, the function politely declines.

**Technically:** `parse_document(path)` recognizes the format by extension: `.docx` is read
with the python-docx library (joining paragraphs), `.pdf` with the pdfplumber library
(joining pages), other extensions are rejected. It returns one continuous text
(`full_text`). An important simplification: quote positions are simply character offsets in
this text, so we do not build a separate "map" of positions onto pages — the very thing the
quote verification from step 1 operates on. The tests create a Word file "on the fly", so
they do not depend on any external sample file.

### Step 7 — The first pipeline phase (`imeto/phases/extract.py`)

**Plainly:** this is the first real "work stage", which ties everything so far into a single
flow: it takes a document, extracts its text, asks the model for facts, **checks every
quote**, and saves to the archive only those facts that are grounded. Facts with a distorted
or invented quote are quietly rejected and counted. At the end the phase reports: "I saved
this many, rejected that many, now a human decision is needed".

**Technically:** we define the phase contract (`Phase`, `PhaseContext`, `PhaseResult` in
`phases/base.py`) and its first implementation — `ExtractPhase`. The flow: `parse_document`
→ save the source → `llm.structured(...)` with an instruction to extract facts → verify
grounds and save the facts. The phase is fully testable with a stub model and a temporary
database. **Note:** the fact model itself (separating a fact from its quotes, the
direct/inferred kinds) was developed later — see [Step 11](#krok-11) and
[chapter 5](#5-jak-wyciagane-sa-fakty), which describes the current flow in full.

### Step 8 — Running from the command line (`imeto/cli.py`)

**Plainly:** the `imeto run <document>` command, which runs the whole flow in one shot and
prints the result: how many facts were saved, how many rejected, and the content of each
fact with its quote. This completes the first working, complete stage of the project (we
call it POC-1).

**Technically:** a thin layer on the Typer library. This is where **the configuration
(step 4) plugs into the core**: the model address and name build the `LLMClient`, `db_url`
builds the database, and `ExtractPhase` processes the document. The CLI contains no logic —
it only calls the core and prints the result (the "interface is a thin skin" rule). If the
model is not configured, the command ends with a readable message instead of an obscure
error.

### Step 9 — The human gate (`imeto/core/provenance.py`)

**Plainly:** until now every verified quote was simply saved. Now we introduce a human
decision: every such quote starts life as a **candidate**, and a human **accepts** or
**rejects** it. The system remembers not only the decision but also its author and the
moment — so it is always clear who approved what. This realizes the "the human decides"
rule.

**Technically:** the decision concerns a **fact** (`Claim`), not a single quote — the fact
gets the fields `status` (candidate / accepted / rejected), `approved_by` (who decided) and
`decided_at` (when). The store has `accept_claim` / `reject_claim` methods and filtering of
facts by status. In the language of the PROV-O standard, acceptance is an attribution to a
person (`wasAttributedTo`), and rejection is an invalidation (`wasInvalidatedBy`). Note: the
full multi-phase "conductor" (sequencer) was deliberately deferred — with a single phase it
would be premature; it will come once there are more phases.

### Step 10 — Graphical interface (`imeto/ui/app.py`)

**Plainly:** a clickable interface in the browser. You upload a document, click "Extract
facts", see a list of candidates, tick the ones you want to accept, and click "Approve". It
is the same flow as on the command line, but convenient for reviewing and making decisions —
the practical realization of the gate from step 9.

**Technically:** the interface is built with the Gradio library, launched with the
`imeto ui` command. We stick to the "interface is a thin skin" rule: the logic (running
extraction, applying decisions) lives in separate, **testable** functions
(`extract_candidates`, `apply_decisions`), and the Gradio layer only wires them to widgets.
We import the Gradio library itself only when the interface is launched, so it does not
burden the rest of the program or the tests. The model address and name can be entered
directly in the interface.

### Step 11 — Typed facts: "direct" vs "inferred" (foundation of POC-2)
<a id="krok-11"></a>

**Plainly:** until now every fact was treated the same. But in real texts a fact is either
**written directly** ("128 people were trained") or **inferred** by the model from several
sentences ("since there were 3 conferences of 100 people each, about 300 people were
reached"). These are two completely different things and **must never be confused** —
because an inference, however credible it sounds, is only the model's reasoning, not a quote.
That is why every fact gets a kind label, and its "grounds" (fragments of the source it rests
on) are still verified to the character. A fact can rest on **multiple** quotes — even from
different places in the document (a dispersed fact).

**Technically:** we split the former single `Evidence` (quote + content) into three
entities: `Claim` (a fact: `statement` + `kind` "direct"/"inferred" + human gate), `Evidence`
(a pure verbatim anchor: quote + position) and `ClaimEvidence` (a **many-to-many** link: a
fact `prov:wasDerivedFrom` its grounds). The model now returns, for each fact: the content,
the kind, and a **list of verbatim ground-quotes** (the "evidence chain"). The save rule: a
fact without a single verified ground = a hallucination → rejected; a fact with some grounds
unverified → saved but flagged "partial" for review. The full run is described in
[chapter 5](#5-jak-wyciagane-sa-fakty).

### Step 12 — Extraction per work type (skills as data)
<a id="krok-12"></a>

**Plainly:** we extract facts not only from reports, but from **various scholarly works** —
articles, reports, proposals, books, posters, presentations. In each of them a "fact" means
something different: in an article it is a result or a method, in a report a completed
activity, and in a proposal — **a plan or a goal, not an accomplishment**. That is why **the
human selects the type** of the uploaded document, and the system picks a matching
instruction ("skill") for it that tells the model what to look for in that type. The
verbatim-quote rule itself and the fact kinds (direct / inferred) remain common to all types.

**Technically:** the work type (`WorkType`: article / report / proposal / book / poster /
presentation) determines the FaBiO class recorded in the source and which skill is appended
to the prompt. Skills use the **Agent Skills format**: each is a `knowledge/extraction/<type>/`
directory with a `SKILL.md` file (a YAML header with metadata + instructions: role, what
counts as a fact, direct vs inferred, type-specific pitfalls) and a `few_shot/` folder with
examples (`*.json`). This is **layer 4** — domain knowledge as **data**, editable by an
expert without touching code; it is loaded by `SkillRegistry` (which strips the header and
appends the examples). The prompt has two parts: a universal base (JSON format, evidence
chain, verbatim requirement, direct/inferred) plus the skill of the chosen type. Crucially:
**one flow and one anti-hallucination mechanism for all types** — the variability sits solely
in the swappable skill files, not in code branches. A new type = a new skill directory, zero
code changes. The type is passed with the `--type` flag on the command line or from a
dropdown in the interface.

### Step 13 — Fetching works via API (metadata anchors)
<a id="krok-13"></a>

**Plainly:** a work does not have to be a file on disk — it can be **fetched from the
internet** by its identifier. Given a **DOI** (a publication number), the system pulls the
title, type and **abstract** from the OpenAlex database; given an **ORCID** (a researcher
identifier), we get a list of their works (their DOIs), which can then be processed one by
one. An important limitation follows directly from our rule: since every fact must have
verbatim grounding in the text, **we extract facts only from text we actually have** — and
via the API that is, by default, the abstract. When a work is openly available (Open Access),
its **full text can be fetched** (the `--full-text` flag): the system downloads the OA PDF
and parses it just like a local file. A full article can be very long (tens of thousands of
characters) and exceeds a small model's context window — which is why long text is **split
into overlapping chunks**, the model processes each separately, and the facts are merged. We
verify quotes against the WHOLE text anyway, so positions stay global (see
[Step 14](#krok-14)).

**Technically:** `imeto/ingest/loaders.py` calls public APIs (OpenAlex by DOI — reconstructs
the abstract from an "inverted index", and also returns the OA `pdf_url`; ORCID by works
list). `fetch_oa_fulltext` fetches and parses the OA PDF (and on any failure returns `None`
and falls back to the abstract — it never aborts). Acquiring the source (from a file or from
an API) is separated from extraction: `imeto/ingest/sources.py` builds the `Source`, and
`ExtractPhase` operates on a ready `source_id`. On the command line:
`imeto ingest --doi <DOI> --type <type> [--full-text]` or `imeto ingest --orcid <ORCID>`. The
`CONTACT_EMAIL` setting serves the API "polite pool".

### Step 14 — Splitting long text into chunks (chunking)
<a id="krok-14"></a>

**Plainly:** a small AI model has limited "working memory" — it cannot read a
tens-of-thousands-of-characters article all at once. So we cut long text into **overlapping
pieces**, the model processes each separately, and the extracted facts are combined into one
list. The overlap ensures that a fact straddling two pieces is not lost; and since the same
fact may then appear twice, **we remove duplicates**. Most importantly: **every quote is
still checked against the whole document**, so positions in the source stay correct
regardless of the split — the verbatim guarantee works the same.

**Technically:** `imeto/core/chunking.py` (`chunk_text`) splits text into chunks of a
configurable length (`CHUNK_CHARS`, 6000 characters by default), cutting on a paragraph or
sentence boundary and with overlap. `ExtractPhase` calls the model once per chunk, collects
the facts, deduplicates them by their quote set, and then verifies grounds against the full
`full_text` (global offsets). Short text (fitting within the threshold) is simply one chunk —
behavior unchanged. The threshold is matched to the model's context window via `CHUNK_CHARS`
in the settings.

---

## 5. How facts are extracted, step by step
<a id="5-jak-wyciagane-sa-fakty"></a>

This is the heart of how IMeTo works. Below is the full run, from the moment you supply a
document to saving a verified fact — first in brief, then each stage in detail, and at the
end a **concrete example** showing how a real quote passes and a made-up one falls out.

### 5.0. The run in brief

```
document → [1] text → [2] save source → [3] ask the model → [4] check the form
        → [5] verify each ground-quote → [6] save facts (direct/inferred)
        → [7] human decision
```

This whole sequence is a single "button press": the `imeto run <document>` command or the
**Extract facts** button in the interface. It launches the `ExtractPhase` phase
(`imeto/phases/extract.py`), which conducts the remaining building blocks.

### 5.1. Stage 1 — from document to clean text

The file (PDF or Word) goes into the `parse_document` function. For Word it glues together
the content of all paragraphs, for a PDF the text of all pages, inserting a newline between
them. The result is **one continuous string** (`full_text`). This matters, because all later
quote positions are simply character offsets in this string — there is no separate "page
map".

### 5.2. Stage 2 — saving the source to the archive

Before we extract anything, the document is saved as a **source** (`Source`) in the database:
its full text, an identifier, and the **work type indicated by the human**, recorded as the
appropriate FaBiO class. The source can come **from a file** (PDF/DOCX) or be **fetched from
an API** by DOI/ORCID (Step 13) — the rest of the run is identical. The source gets its
number (`source_id`); this gives every future fact something to "attach" to, and it is always
clear which document (and of which type) it came from.

### 5.3. Stage 3 — asking the AI model

We send the model two things:

- **An instruction**, made of two parts: **the base** (the fixed `EXTRACT_SYSTEM` text) —
  "extract facts; return only JSON in the format `{"facts": [{"statement": "...", "kind":
  "direct|inferred", "quotes": ["..."]}]}`; quotes must be verbatim fragments of the text;
  every fact must have at least one quote; do not make things up" — plus the **skill of the
  chosen** work type (`knowledge/extraction/<type>.md`), which spells out *what counts as a
  fact* in that kind of document (e.g. in a proposal: a plan/goal, not an accomplishment).
  See [Step 12](#krok-12).
- **The document content** (`full_text`) as the material to read.

The model is to return a list of facts, where each fact has three elements:

- **`statement`** — the fact in the model's own words (for a human to read),
- **`kind`** — the fact's kind: **`direct`** (written in the text directly) or **`inferred`**
  (inferred by the model from the text). These two **never blur together** — see
  [Step 11](#krok-11),
- **`quotes`** — a list of **verbatim** source fragments the fact rests on (the "evidence
  chain"). For a `direct` fact this is its support; for an `inferred` fact these are the
  **premises** of the inference. A fact can have multiple quotes — also from different places
  in the document (a dispersed fact).

Note what is **not** here: the model does **not** state where in the text the quotes are. We
compute the positions ourselves (stage 5), because that is the only way not to be fooled.

### 5.4. Stage 4 — checking that the response has the right form

The model's response passes through `LLMClient.structured`:

1. If the model wrapped the JSON in a ```` ```json … ``` ```` block, we strip that wrapper
   (small models often do this).
2. We try to read and **validate** the result against the schema (`Extraction`): is it valid
   JSON, are the `statement`, `kind` (only "direct"/"inferred") and `quotes` (at least one)
   fields present, are they non-empty, is there no junk field.
3. If validation fails, we append an error message to the conversation ("the previous
   response did not meet the schema, correct it") and **ask the model again**, up to a set
   attempt limit. Once attempts are exhausted we raise a readable error.

This is the first of two safety nets: it guards the **form** of the response. The second
(stage 5) guards its **truthfulness**.

### 5.5. Stage 5 — verifying each ground-quote (the heart of anti-hallucination)

For **each quote** in a given fact's `quotes` list we run `add_evidence`, which does not take
the model's word for it but checks the quote against the original via the `find_span`
function:

1. We take the quote and strip surrounding spaces.
2. We split it into words and build the pattern "word — any whitespace — word — …". This way
   **non-whitespace characters (letters, digits, punctuation) must match to the character**,
   but differences in spaces or line breaks are tolerated (the model often collapses text).
3. We search for this pattern in the source's `full_text`.
   - **Found** → we create a **ground** (`Evidence`): the verbatim quote, the position
     `(start, end)` in the original, and a provenance "pedigree" (which process, which model,
     when).
   - **Not found** → no ground is created (`SpanNotVerified`); this quote does not count.

### 5.6. Stage 6 — assembling the fact from its grounds (the save rule)

Once all of a fact's quotes have been verified, we look at how many of them were confirmed:

- **Zero confirmed grounds** → the fact is baseless (a hallucination) and is **not created**;
  we count it as rejected.
- **At least one confirmed ground** → we save the fact as a `Claim` (with its `kind`) and
  link it to all confirmed grounds (a many-to-many link). If some quotes fell out, the fact
  is additionally flagged **"partial"** — for the human's attention.

Facts are born with status **`candidate`**. The phase returns a summary: how many facts were
saved (including partial ones), how many were rejected for lack of grounding, and a "human
decision needed" signal (`needs_human`). Crucially: **a "direct" fact and an "inferred" fact
are saved with different labels and never look the same** — the human immediately sees what
is a quote and what is the model's inference.

### 5.7. Stage 7 — the human decision (gate)

A candidate is not yet an approved fact. The human reviews the list and **accepts** or
**rejects** each **fact** individually (seeing its kind and all its grounds). The decision
changes the fact's (`Claim`) status to `accepted` or `rejected` and records **who** made it
and **when**. Only accepted facts are considered confirmed. This realizes the "the human
decides" rule (the system never pushes conclusions through on its own).

### 5.8. Concrete examples

**Example 1 — a direct fact, quote verification.** The document contains the sentence:

> `The council adopted resolution no. 12 concerning the budget for 2025.`

| Fact (`kind`) | `quotes` (grounds) | Result |
|---|---|---|
| "The council adopted a resolution" (`direct`) | `["adopted resolution no. 12"]` | **Found** → fact saved, ground at position e.g. (12, 37) |
| "The council adopted resolution no. 13" (`direct`) | `["adopted resolution no. 13"]` | **Not found** (12 ≠ 13) → no ground → fact **rejected** |

The second fact looks equally credible, but the model got the number wrong — the original
has no "no. 13", so it drops out automatically. (Conversely: collapsing a space or a line
break is tolerated, because the non-whitespace characters match.)

**Example 2 — an inferred fact, multiple grounds.** The document has two sentences:

> `3 conferences were organized.` … `Each conference drew 100 people.`

| Fact (`kind`) | `quotes` (premises) | Result |
|---|---|---|
| "The conferences covered about 300 people" (`inferred`) | `["3 conferences", "100 people"]` | **Both found** → fact saved as inferred, linked to two grounds |

Here the conclusion ("300 people") **is not in the text** — it is the model's inference. We
do not try to anchor it; we anchor its **premises** (both verbatim confirmed), and flag the
fact itself as `inferred`, so the human can judge whether the inferential leap is sound. Had
one of the premises not occurred in the text, the fact would be flagged "partial" (or
rejected, had none been confirmed).

These examples are at the same time real tests in the code
(`tests/test_span_verification.py`, `tests/test_extract_phase.py`).

---

## 6. Data model and standards compliance
<a id="6-model-danych-i-zgodnosc-ze-standardami"></a>

This is a deliberate and important design decision. Instead of inventing our own private way
of describing data, **we describe the data in the language of recognized international
standards**. As a result, what IMeTo produces is understandable to other scholarly systems
and can be exchanged, cited, and audited.

**Plainly:** it is a bit like using ISO for dates or a bibliographic standard in a library —
we do not invent our own format, we stick to what the world has already agreed on. Our
database is still a plain, simple database, but **the field names and types correspond to
these standards**, and ultimately the data can be exported to a format that other scholarly
systems understand out of the box.

Four standards, each responsible for a different layer (they do not compete):

| Standard | What it is responsible for in IMeTo | Example |
|---|---|---|
| **PROV-O** (W3C) | **Data provenance** — who/what/when produced a given fact | evidence "was quoted from" a source, "was generated by" a given process |
| **Web Annotation** (W3C) | **Anchoring a quote** in the text | "this quote is characters 120 to 145 in the document" |
| **FaBiO** (SPAR) | **Type of the source document** | report, research article, thesis, dataset |
| **SKG-IF** | **Exchange format** for scholarly metadata | identifiers (DOI, ORCID), authors, journals |
| **SKOS** | **Domain vocabularies** (planned) | list of evidence types, assessment criteria |
| **CiTO** (SPAR) | **Argumentative relations** (planned, POC-2) | this ground "supports" / "refutes" this statement |

How this looks concretely in the database (three entities):

- **`Source`** (a document) is described as an "entity" in the PROV-O sense, typed by a FaBiO
  class (e.g. "report"), with bibliographic fields from the Dublin Core standard (title,
  language) and a list of identifiers in the SKG-IF model (e.g. DOI).
- **`Evidence`** (a ground — a verified quote) combines two standards: it is a PROV-O
  "entity" that "was quoted from" the source (`prov:wasQuotedFrom`), and at the same time an
  "annotation" in the Web Annotation sense — the exact quote is a text selector (`exact`),
  and the from-to position is a position selector (`start`/`end`). Plus the provenance
  fields.
- **`Claim`** (a fact) is a PROV-O "entity" that **`prov:wasDerivedFrom`** its grounds
  (through the many-to-many `ClaimEvidence` link). It carries the content, the kind (`direct`
  / `inferred`), the provenance, and the human-gate state (candidate / accepted / rejected).
  Separating the fact (`Claim`) from the ground (`Evidence`) is precisely what lets one fact
  rest on multiple quotes and distinguishes a quoted fact from an inferred one.

**Storage decision:** we stay with a plain relational database (SQLite), and we realize
standards compliance through **field naming** and through **export to JSON-LD** (planned for
a later stage). We do not build a special "graph database" or an RDF triple store — for a
single local user that would be needless overhead. A curiosity: our data *is* a graph (PROV-O
is a graph model), and the JSON-LD export *is* a graph — so anyone who wants graph analyses
can load the exported dossier into a graph tool of their own. We get the graph "on the way
in" (the model) and "on the way out" (the export), without a graph engine in the middle.

---

## 7. How to run and check it
<a id="7-jak-to-uruchomic-i-sprawdzic"></a>

All commands are run in the project directory
(`/Users/patrykhubar/Desktop/imeto_2_0`). We use the `uv` tool to manage the environment —
`uv run` runs a command in the project environment.

**Install the environment (once):**
```bash
uv sync --extra dev
```

**Run all the tests** — this is the "proof that everything works":
```bash
uv run pytest -v
```
You will see a list of tests ending in `PASSED`. The test files in the `tests/` directory
read like a specification — each test is one described case.

**Check code quality** (style and types):
```bash
uv run ruff check imeto tests   # style and common errors
uv run mypy imeto               # type consistency
```

**Play with quote verification live:**
```bash
uv run python
```
and then in the interactive console:
```python
from imeto.core.span import find_span
src = "The council adopted resolution no. 12\nconcerning the budget."
find_span(src, "adopted resolution no. 12")   # -> (12, 37)  found
find_span(src, "adopted resolution no. 13")   # -> None      (wrong digit)
```

**Run the whole flow on a document (POC-1):** you need a working AI model (local,
OpenAI-API-compatible). We point to it in the settings, and then:
```bash
export LLM_BASE_URL="http://localhost:8888/v1"   # your model's address
export LLM_MODEL="<model name>"                  # e.g. from Unsloth Studio / vLLM
uv run imeto run data/sprawozdanie_test.docx --type report
```
The `--type` flag (required) tells the document's type: `article`, `report`, `proposal`,
`book`, `poster` or `presentation`. The program will print a summary (how many facts were
saved — including partial ones — how many rejected as ungrounded) and each fact with its kind
(`direct`/`inferred`) and verbatim ground-quotes. Without a configured model the command
raises a readable message "llm_model not set" — this is correct behavior.

**Fetch a work from the internet (instead of a file):**
```bash
uv run imeto ingest --doi 10.1234/przyklad --type article              # from the abstract
uv run imeto ingest --doi 10.1234/przyklad --type article --full-text  # OA full text
uv run imeto ingest --orcid 0000-0002-1825-0097                        # researcher's works list
```
`--doi` pulls metadata and the abstract from OpenAlex and extracts facts right away;
`--full-text` additionally fetches the Open Access full text (PDF) if available; `--orcid`
prints a list of works (DOIs) for further processing. Note: via the API we usually have only
the abstract.

---

## 8. What comes next on the roadmap
<a id="8-co-jest-dalej-w-planie"></a>

Built: **steps 0–13** — the entire POC-1 flow (skeleton, quote verification, data contract,
provenance database, settings, AI client, document loading, extraction phase, command line,
human gate, Gradio GUI), the **foundation of POC-2** — typed facts (direct / inferred) with
multiple verbatim-anchored grounds (Step 11), **per-work-type extraction** with skills in the
Agent Skills format (Step 12), **fetching works via API** (DOI/ORCID + OA full text, Step 13)
and **splitting long text into chunks** (Step 14).

Launching the interface:
```bash
uv sync --extra ui          # install Gradio (once)
uv run imeto ui             # open the interface in the browser
```

Next steps: more work types, **lead suggestions and FOR/AGAINST argumentative analysis**
(CiTO relations) — i.e. turning facts into an assessment under Criterion III, the editorial
assistant, dossier export (including JSON-LD), a statement map. Conditionally: the multi-phase
"conductor" (sequencer), Postgres, real APIs. Model fine-tuning is deliberately deferred —
first prompts, few-shot in skills, and a golden set (we have: recall 0.98 / precision 0.97 /
kind 0.98 over 18 cases).

---

## Glossary
<a id="slownik-pojec"></a>

- **AI / language model (LLM)** — a program that generates text from instructions (like
  ChatGPT). Powerful, but sometimes unreliable — hence all our caution.
- **Hallucination** — a situation where the model states information that sounds credible but
  is made up or distorted.
- **Quote / span** — a verbatim fragment of the source text. A "span" is its position: from
  which character to which it occurs in the document.
- **Anchoring** — linking a quote to its exact place in the source.
- **Fact (`Claim`)** — a statement extracted from a document. It has a kind (`kind`) and rests
  on one or more grounds. It is what the human accepts/rejects.
- **"direct" fact** — written in the source verbatim; the grounds are its direct support.
- **"inferred" fact** — a conclusion not present verbatim in the text; the model drew it. The
  grounds are its **premises**. We never confuse it with a "direct" fact.
- **Ground (`Evidence`)** — a verbatim-anchored quote supporting a fact. One fact can have
  multiple grounds (a dispersed fact), and a ground can serve multiple facts.
- **Evidence chain** — the requirement that for each fact the model point to the verbatim
  source fragments the fact rests on. The absence of such a fragment = a hallucination
  signal.
- **Work type (`WorkType`)** — the kind of document being processed: article, report,
  proposal (more eventually). Indicated by the human at import. It determines the source's
  FaBiO class and which extraction skill is used.
- **Skill / knowledge layer** — a domain instruction in the Agent Skills format: a
  `knowledge/extraction/<type>/` directory with `SKILL.md` (header + instructions) and
  `few_shot` examples. Appended to the prompt for a given work type. This is "knowledge as
  data": an expert tunes extraction without touching code.
- **Metadata anchor (DOI / ORCID / OpenAlex)** — fetching a work from a public API: **DOI**
  is a publication identifier (OpenAlex returns its title, type and abstract), **ORCID** is a
  researcher identifier (returns a list of their works). A source of deterministic metadata,
  complementing local files.
- **Provenance** — information about where a given fact came from: from which source, in which
  process, through which model, when. It lets any piece of information be reconstructed and
  audited.
- **Invariant** — a rule that must always hold. For us: "evidence only after quote
  verification".
- **Structured output** — the requirement that the model respond in a strictly defined form
  (a form), not in arbitrary text.
- **Schema / data contract** — a description of the allowed form of data: which fields, of
  which types, what is mandatory.
- **Validation** — checking whether data meets the schema.
- **Ontology / data-description standard** — a community-agreed way of naming and linking
  concepts, so that different systems understand the same data the same way. PROV-O, FaBiO,
  SKOS, Web Annotation, SKG-IF are such standards.
- **JSON-LD** — a data format that is at once a plain data file and an ontology-compliant
  graph. Our planned export format.
- **Relational database / SQLite** — a way of storing data in tables. SQLite is its simplest
  variant: the whole database is a single file, with no separate server.
- **Pipeline** — a sequence of stages a document passes through.
- **Gate (human-in-the-loop)** — a moment where the system waits for a human decision.
- **Core vs phases** — the core is the shared building blocks (general), the phases are the
  concrete pipeline stages (domain-specific). Phases use the core, never the other way
  around.
- **Test** — a small program that checks that a given piece of code does what it should.
  "Green tests" mean everything passed.
- **on-premise (on-prem)** — running on your own hardware, without the cloud and without
  sending data outside.
- **`uv`, `ruff`, `mypy`, `pytest`** — the working tools: `uv` manages the environment,
  `ruff` enforces code style, `mypy` checks type consistency, `pytest` runs the tests.
