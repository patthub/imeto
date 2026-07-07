"""Structured output LLM-a (ADR-003). Twardy kontrakt formatu: model zwraca
wyłącznie te pola. Cytaty (`quotes`) są weryfikowane osobno przez `core.span`;
offsetów model NIE podaje — liczymy je sami.

Zasada „łańcucha dowodów": każdy fakt musi wskazać dosłowne fragmenty źródła,
na których się opiera (>=1). Rodzaj faktu (`kind`) rozdziela to, co napisane
wprost, od tego, co wywnioskowane — te dwa nigdy się nie zlewają."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# direct   — fakt napisany w źródle wprost; `quotes` to jego dosłowne poparcie.
# inferred — fakt wywnioskowany; `quotes` to PRZESŁANKI, na których wniosek się opiera.
FactKind = Literal["direct", "inferred"]


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: NonBlank  # fakt (własnymi słowami)
    kind: FactKind
    quotes: list[NonBlank] = Field(min_length=1)  # dosłowne grunty/przesłanki


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact]


# za — fakt wspiera spełnienie kryterium; przeciw — podważa; luka — istotny brak.
ArgSide = Literal["za", "przeciw", "luka"]


class ProposedArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: ArgSide
    statement: NonBlank  # argument własnymi słowami
    based_on: list[int]  # numery FAKTÓW (1-based), na których argument się opiera


class Argumentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: list[ProposedArgument]


class Corroboration(BaseModel):
    """Werdykt: czy zewnętrzna strona potwierdza społeczny wpływ danego faktu."""

    model_config = ConfigDict(extra="forbid")

    confirms: bool
    quote: str = ""  # DOSŁOWNY cytat ze strony potwierdzający wpływ (gdy confirms)
