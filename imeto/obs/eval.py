"""Golden-set eval (§12) — measures extraction quality with our own script, no cloud.

`score()` is pure and testable without a model (matches facts by grounds coverage,
not by verbatim statement content). `run_case()` runs a real model on the cases in
`tests/golden/*.json` and computes metrics: recall, precision, and kind accuracy."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from imeto.core.llm import LLMClient
from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.span import _fold
from imeto.phases.base import PhaseContext
from imeto.phases.extract import ExtractPhase
from imeto.registries.skills import SkillRegistry
from imeto.worktypes import WorkType


@dataclass
class ExpectedFact:
    kind: str
    quote_substrings: list[str]  # distinctive fragments expected in the grounds


@dataclass
class PredictedFact:
    kind: str
    grounds: list[str]


@dataclass
class Metrics:
    n_expected: int
    n_predicted: int
    matched: int
    recall: float
    precision: float
    kind_accuracy: float


def _hit(grounds: list[str], substrings: list[str]) -> bool:
    hay = _fold(" ".join(grounds)).lower()
    return any(_fold(s).lower() in hay for s in substrings)


def score(predicted: list[PredictedFact], expected: list[ExpectedFact]) -> Metrics:
    """Greedy matching: an expected fact hits when some not-yet-used predicted
    fact has one of its distinctive fragments in its grounds."""
    used: set[int] = set()
    kind_ok = 0
    for exp in expected:
        for i, pred in enumerate(predicted):
            if i in used or not _hit(pred.grounds, exp.quote_substrings):
                continue
            used.add(i)
            if pred.kind == exp.kind:
                kind_ok += 1
            break
    matched = len(used)
    recall = matched / len(expected) if expected else 1.0
    precision = (
        matched / len(predicted) if predicted else (1.0 if not expected else 0.0)
    )
    kind_accuracy = kind_ok / matched if matched else 1.0
    return Metrics(
        len(expected), len(predicted), matched, recall, precision, kind_accuracy
    )


def aggregate(metrics: list[Metrics]) -> Metrics:
    if not metrics:
        return Metrics(0, 0, 0, 1.0, 1.0, 1.0)
    n = len(metrics)
    return Metrics(
        sum(m.n_expected for m in metrics),
        sum(m.n_predicted for m in metrics),
        sum(m.matched for m in metrics),
        sum(m.recall for m in metrics) / n,
        sum(m.precision for m in metrics) / n,
        sum(m.kind_accuracy for m in metrics) / n,
    )


def load_golden(directory: str | Path) -> list[dict[str, Any]]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(Path(directory).glob("*.json"))
    ]


def run_case(case: dict[str, Any], llm: LLMClient, skills: SkillRegistry) -> Metrics:
    """Runs extraction on a single case (fresh in-memory store) and scores it."""
    store = ProvenanceStore()  # in-memory — doesn't touch the real store
    sid = store.add_source(
        Source(local_identifier=case["name"], full_text=case["text"])
    )
    ExtractPhase(sid, WorkType(case["work_type"])).run(
        PhaseContext(store=store, llm=llm, skills=skills)
    )
    predicted: list[PredictedFact] = []
    for claim in store.claims_for_source(sid):
        assert claim.id is not None
        grounds = [ev.quote for ev in store.evidence_for_claim(claim.id)]
        predicted.append(PredictedFact(kind=claim.kind, grounds=grounds))
    expected = [ExpectedFact(**e) for e in case["expected"]]
    return score(predicted, expected)
