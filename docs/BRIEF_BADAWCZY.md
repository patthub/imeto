# IMeTo — project brief and research direction

A document for a **separate, theoretical/research thread** on argument mining, scientific
reasoning, evidence and plausibility. It gathers (1) what the project is and what already
works, and (2) where we want to go on the research side. The "production" implementation
proceeds separately, more simply, without research — this document does NOT concern it beyond
background.

State as of 2026-07-14. Code: ~111 green tests (pytest/ruff/mypy strict). Local repo, local
model (gemma-4-E2B via Unsloth, OpenAI-compatible). Some of the data changes described below
(`external_trail`, the `Lead` table) are implemented but **not yet committed** and **not
verified against a live model**.

---

## PART 1 — What IMeTo is and what has already been built

### 1.1 Goal
A single-person, on-prem pipeline that **extracts facts from documents** (PDF/DOCX, Polish
reports and scholarly works) and **anchors every fact in a verbatim source fragment**
(provenance). The core value = **anti-hallucination through provenance**: no fact enters the
store without a verified, character-exact span in the source. Target application:
**Criterion III** of the evaluation of research units — *the impact of scholarly activity on
the functioning of society and the economy*, with a CAUSAL, documented link between the
research and the effect.

### 1.2 Inviolable rules (from TECHNICZNY.md)
- **Sync core, async only at the API edge.** The core (phases, provenance, extraction) is
  synchronous.
- **Model-agnosticism.** The only touch point with the model = OpenAI Chat Completions via
  `LLM_BASE_URL`/`LLM_MODEL`. No provider-locking SDKs. Swapping the model = zero code
  changes.
- **All database access through `ProvenanceStore`.** No other module touches SQL (a cheap
  SQLite→Postgres path, one SQLModel model).
- **Provenance invariants in code, not just in the schema.** `add_evidence` accepts a record
  only after span verification (`core.span`, pure Python).
- **Tools return CANDIDATES, not verdicts.** The human decides what is evidence.
- **Typed, centralized configuration** (`pydantic-settings`).
- **Every core module testable without a live model** (mock LLM). Model quality measured
  separately by eval, not by unit tests.

### 1.3 Architecture
- **`core/`** — `llm.py` (OpenAI-compatible client + validation/retry), `schemas.py`
  (Pydantic structured output), `provenance.py` (`ProvenanceStore`), `span.py` (verbatim
  quote verification), `chunking.py` (splitting long text).
- **`phases/`** — `extract.py`, `suggest.py`, `corroborate.py`, `argumenter.py`; each phase
  `run(ctx) -> PhaseResult`. Phases depend on `core/`, never the reverse.
- **`registries/`** — `SkillRegistry` (domain knowledge as DATA: `knowledge/**.md` +
  few-shot, loaded into prompts).
- **`ingest/`** — source acquisition (file, DOI/OpenAlex, ORCID, URL, OA full text).
- **`ui/`** (Gradio) and **CLI** (Typer) — thin skins, logic in the core.

### 1.4 Data model (current)
A fact = `Claim` + its evidence. There is NO separate "Fact" entity — it is `Claim` + a view.
- **`Source`** — the source document (prov:Entity, FaBiO type).
- **`Claim`** — a fact: `statement`, `kind` ∈ {`direct` = written directly, `inferred` =
  inferred}, human gate (`status`: candidate|accepted|rejected), provenance
  (`generated_by_activity`, `attributed_to_agent`), and **`external_trail`** ∈
  {unknown|internal|candidate} — the suggester's hint (not a gate) as to whether the fact has
  a trace of external impact to look for.
- **`Evidence`** — a verbatim anchor: `quote`, `start`, `end` (oa:TextQuoteSelector +
  TextPositionSelector). An "own" ground (same source as the fact) vs an external
  confirmation (a different source) is distinguished by `source_id`.
- **`ClaimEvidence`** — N:M fact↔ground (prov:wasDerivedFrom). Supports dispersed facts
  (multiple grounds) and facts with external confirmation (corroboration).
- **`Lead`** — an impact lead pinned to a fact: `lead` (what to look for) + `query` (an
  EDITABLE query). A candidate (Z1), one per fact.
- **`Argument`** + **`ArgumentClaim`** — an assessment per rubric (FOR/AGAINST/GAP), N:M with
  the facts it rests on. A structure parallel to Claim↔Evidence, one level up.

Alignment with standards via column naming + a planned JSON-LD export (NOT a triplestore):
**PROV-O** (columns), **FaBiO** (source type), **DCTerms**, **SKG-IF** (identifiers), **Web
Annotation / oa** (quote anchor), **SKOS**.

### 1.5 The loop (pipeline)
`extract` (document → facts with grounds; direct/inferred; a fact without a verified ground =
hallucination → rejected) → **human gate** (accept/reject) → `suggest` (leads: what and with
which query to search for as impact evidence; sets `external_trail`, saves `Lead`) →
`corroborate` (web search per lead → fetch the page → LLM: does it confirm the impact of THIS
research + a verbatim quote → span verification on the page → external evidence pinned to the
fact) → `argue` (accepted facts → FOR/AGAINST/GAP arguments per the Criterion III rubric; a
fact with external confirmation = DOCUMENTED impact, a stronger FOR).

The "dossier" (internal+external) is realized without a separate table: corroboration links
external evidence to internal facts, and the argumenter sees them.

### 1.6 State and key empirical findings
- The POC works end-to-end (CLI + Gradio GUI with a fact table: No. | Kind | Fact | Quote |
  Position | Context ±120 chars | Trail/query | Impact).
- **Extraction quality measured** on a golden set (18 cases, 6 work types): recall ~0.98 /
  precision ~0.97 / kind ~0.98. The rest of the gaps are real model behavior.
- **Known limitations, model-side (not code):** PDF extraction quality limits recall on real
  papers (merged words → verification rejects); speed ~60s/chunk on E2B (drops sharply under
  memory/swap pressure); **nondeterminism even at temp=0** (float-reduction in
  llama.cpp/Metal) → a single eval is noisy, a small golden set is not enough for stable
  aggregates.
- **Corroboration precision problem (relevant to part 2):** the search caught pages with
  similar WORDS unrelated to the research (e.g. the fact "ecological debates" → a document on
  ecological education; "published Apr 2021" → the methodology of a Statistics Poland census).
  Causes: (a) a query based on a single fact's content without the research context; (b)
  corroboration tried to confirm EVERY fact, including purely internal ones (dates, metadata);
  (c) the verdict accepted the same TOPIC instead of the same RESEARCH. Partially fixed
  (research context in the query and verdict, suggester selectivity, a stricter verdict), but
  this is **confirmation bias** — the system looks only for confirmations. This is the thread
  part 2 wants to attack at its root.
- **Fine-tuning: deferred so far** (it breaks model-agnosticism; the gate = a golden set +
  proven plateau). Now reconsidered in a research context (part 2).

---

## PART 2 — Research direction: scientific argumentation, evidence, plausibility

### 2.1 The guiding move
From "extract facts" to **"extract and TEST the argument's structure"**. IMeTo already has
provenance as its backbone — which almost no argumentation tool has. The thesis:
**plausibility grounded in provenance** is an original, defensible (and publishable)
position.

### 2.2 The direction fork (resolved toward B)
- **(A) The model generates reasoning** — it posits theses itself, weighs evidence, rules on
  plausibility. Tempting, but this is the main source of convincing nonsense; it strikes at
  IMeTo's DNA.
- **(B) The model extracts and tests someone else's argumentation** — the argument's skeleton
  anchored in the text, marking stated vs inferred, plausibility as an explicit, decomposed,
  auditable judgment handed to the human. **Chosen.**

### 2.3 Relations as facts about facts (the core of the model extension)
Directions "X **follows from** Y" and "X **influenced** Y" are statements — like a fact, they
can be `stated` (a verbatim link in the text) or `inferred` (a model leap). Proposed entity:

```
FactRelation
├─ from_claim → to_claim              (DIRECTION matters)
├─ type    follows_from | influences       (a small vocabulary; = logical / causal warrant)
├─ kind    stated | inferred
├─ evidence   (if stated — the quote with the connective, verified = Toulmin's "backing")
└─ status     candidate | accepted | rejected   (human gate)
```

A structure parallel to `ClaimEvidence`/`ArgumentClaim`, but directed and typed. It sits on
**Toulmin** (claim/data/**warrant**/**backing**/qualifier/rebuttal) and on standards (PROV-O
`wasInfluencedBy`/`wasDerivedFrom`, CiTO, possibly **AIF**).

**Principle (from EBR, Brown et al. 2010): a fact's role is RELATIONAL, not semantic.** The
same sentence is at times a premise, a conclusion, or a datum — depending on its neighbors.
Consequence: **we do not add fact-role types** (premise/conclusion/datum); roles emerge from
the edges.

### 2.4 Plausibility — not a number, but a decomposed, defeasible judgment
- **Toulmin's qualifier + rebuttal** is plausibility made structural: qualifier = degree of
  strength (presumably/probably), rebuttal/**defeaters** = conditions under which the claim
  falls.
- **Walton: argumentation schemes + critical questions.** Instead of "rate plausibility 0–1"
  (the model guesses), you give a scheme (e.g. argument from expert opinion) and its critical
  questions (is E an expert in this field? biased? do others agree?) — the model answers
  concrete, checkable questions, and the human sees the answers.
- **Pollock: rebutting vs undercutting defeaters** — rebutting attacks the conclusion (the
  evidence level), undercutting attacks the warrant/inference (the relation level). It maps
  directly onto ground-vs-relation → plausibility decomposed and auditable.
- **Actively hunting for defeaters** as a cure for confirmation bias (the problem in §1.6):
  instead of "find a confirmation", also "what undermines this link? is there an alternative
  explanation of the effect independent of the research?".

### 2.5 Takeaways from the EBR paper (Brown et al. 2010, Educational Assessment)
- warrant = "explanation why the claim follows **logically or causally** from data" —
  confirms the split into `follows_from`/`influences`; backing = evidence for the warrant.
- "Assess the supporting structure, not the claim itself" (raw right/wrong short-circuits the
  assessment) — reinforces the provenance principle.
- **Validity ≠ accuracy**: whether the conclusion follows (structure) vs whether the premises
  are true (content) — two separate axes, useful for inferred relations (a lens for now, not
  a field).
- **Warrants are usually UNstated** → expect most relations to be `inferred`, few `stated`;
  the few signal CONNECTIVES ("thanks to which", "as a result of", "which led to") — a
  ready-made recipe for the `relate` phase prompt.

### 2.6 Position on fine-tuning (research-wise)
- Not "yes/no", but **"for what and how will I measure it"**. Without a goal + a ruler it is
  gambling.
- **Invest in a CORPUS + EVAL, not in weights.** A hand-annotated corpus of argumentation on
  Polish texts = an evaluation set + training data + paper material; it survives every pivot.
  This makes "we can drop it" true.
- Fine-tune is **good for FORM** (reliable filling of scheme slots / critical questions in a
  small model), **bad for** truth/knowledge/hallucination.
- **Model-agnosticism stays:** a fine-tuned model = one pluggable backend for comparison (via
  `LLM_MODEL`), not a system requirement. The core is swappable, the experiment is a branch.
- The empirical gate: fine-tune only once the prompt hits a plateau on a NAMED error class
  and there is enough data.

### 2.7 Research questions
1. Can a small model reliably point to the **warrant** (an unstated link) and rule stated vs
   inferred?
2. Does **decomposition via critical questions** yield a better-**calibrated** plausibility
   than a holistic "rate 0–1"?
3. Does **actively hunting for defeaters** reduce false confirmations from confirmation bias
   (the real problem in §1.6)?
4. Does **grounding in provenance** make plausibility auditable/reproducible in a way a
   purely-LLM judgment is not?

### 2.8 Literature / frameworks to pull
- **Argument mining** — Stab & Gurevych; Lawrence & Reed (extracting argument structure from
  text; annotation schemes, datasets).
- **AIF (Argument Interchange Format)** — a standard for representing arguments (analogous to
  the alignment with PROV-O/FaBiO; `FactRelation` could sit on it).
- **Toulmin** (Uses of Argument) — claim/data/warrant/backing/qualifier/rebuttal.
- **Walton** — argumentation schemes + critical questions.
- **Pollock** — rebutting vs undercutting defeaters, defeasible reasoning.
- **Hahn & Oaksford** — Bayesian argumentation (plausibility as a degree of support).
- **GRADE** (EBM/medicine) — systematic hierarchies of evidence strength.
- **EBR Framework** — Brown, Furtak, Timms, Nagashima, Wilson (2010), Educational Assessment
  15(2), DOI 10.1080/10627197.2010.530551.
- Model confidence calibration (whether "confidence" is calibrated).

### 2.9 First research move (cheap, irreversibly valuable)
Take 5–10 real fragments (Polish reports / a paper) and **annotate them by hand** per the
chosen scheme (extended Toulmin or Walton's schemes with critical questions). This reveals
what is hard and yields a golden seed. Then: the prompt does the same → comparison → an
**error taxonomy** (already a research result) → possibly a fine-tune, once the prompt
plateaus on a named error class.

---

## Work split (two tracks)
- **Research track (separate thread):** the theory from §2, designing the annotation scheme,
  a manual corpus, eval, an error taxonomy, a possible fine-tune. This document feeds it.
- **Implementation track (main repo, here):** simpler improvements without research — the
  fact data model (`external_trail` + `Lead` already exist), the fact table in the GUI, an
  editable query widget before corroboration, verification against a live model. No
  argumentation theory.
