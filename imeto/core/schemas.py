"""Structured output LLM-a (ADR-003). Twardy kontrakt formatu: model zwraca
wyłącznie te pola. `quote` jest weryfikowany osobno przez `core.span`; offsetów
model NIE podaje — liczymy je sami, nie ufamy modelowi."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: NonBlank  # dosłowny fragment źródła (do weryfikacji spanu)
    statement: NonBlank  # fakt, który cytat popiera


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact]
