"""LLM structured output (ADR-003). A hard format contract: the model returns
only these fields. Quotes (`quotes`) are verified separately by `core.span`; the
model does NOT supply offsets — we compute them ourselves.

The "chain of evidence" rule: every fact must point to the verbatim source
fragments it rests on (>=1). A fact's `kind` separates what is stated explicitly
from what is inferred — the two never conflate."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# direct   — fact stated explicitly in the source; `quotes` are its verbatim support.
# inferred — inferred fact; `quotes` are the PREMISES the inference rests on.
FactKind = Literal["direct", "inferred"]


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: NonBlank  # fact (in your own words)
    kind: FactKind
    quotes: list[NonBlank] = Field(min_length=1)  # verbatim grounds/premises


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact]


# for — fact supports meeting the criterion; against — undermines it; gap — a key gap.
ArgSide = Literal["for", "against", "gap"]


class ProposedArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: ArgSide
    statement: NonBlank  # argument in your own words
    based_on: list[int]  # FACT numbers (1-based) the argument rests on


class Argumentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: list[ProposedArgument]


class Corroboration(BaseModel):
    """Verdict: does an external page confirm the given fact's societal impact."""

    model_config = ConfigDict(extra="forbid")

    confirms: bool
    quote: str = ""  # VERBATIM quote from the page confirming impact (when confirms)


class ImpactLead(BaseModel):
    """Lead: for a given fact — what EVIDENCE of societal impact to search the web
    for, and with what query. A suggestion (candidate), not a fact — it does not
    enter provenance. `internal` is the model's HINT that the fact likely has no
    external impact trace; it is shown to the human but does NOT gate the search."""

    model_config = ConfigDict(extra="forbid")

    based_on: int  # FACT number (1-based) the lead concerns
    internal: bool = False  # model's hint: fact likely has no external impact trace
    lead: NonBlank  # what to search for: which external impact trail of this fact
    query: NonBlank  # search-engine query (aimed at impact, not the fact itself)


class LeadSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leads: list[ImpactLead]
