from pathlib import Path

import httpx
import pytest
import respx
from docx import Document

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import (
    Argumentation,
    Corroboration,
    ExtractedFact,
    Extraction,
    ProposedArgument,
)
from imeto.phases import corroborate as C
from imeto.registries.skills import SkillRegistry
from imeto.tools.web_search import SearchResult
from imeto.ui.app import (
    apply_argument_decisions,
    apply_decisions,
    argue_candidates,
    corroborate_facts,
    extract_candidates,
    extract_candidates_from_doi,
    extract_candidates_from_url,
)
from imeto.worktypes import WorkType


class FakeLLM:
    model = "fake"

    def __init__(self, ex: object) -> None:
        self._ex = ex

    def structured(self, system: str, user: str, schema: type) -> object:
        return self._ex


def _make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("Rada gminy przyjęła uchwałę nr 12 w sprawie budżetu.")
    doc.save(str(path))
    return path


def _skills(tmp_path: Path) -> SkillRegistry:
    base = tmp_path / "knowledge"
    for sub, name in [("extraction", "report"), ("extraction", "article")]:
        d = base / sub / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("## Rola\ntest", encoding="utf-8")
    crit = base / "criteria" / "kryterium_iii"
    crit.mkdir(parents=True)
    (crit / "SKILL.md").write_text("## Rubryka\ntest", encoding="utf-8")
    return SkillRegistry(base)


def test_extract_candidates_returns_source_and_labels(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx")
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(
                statement="Rada przyjęła.", kind="direct", quotes=["uchwałę nr 12"]
            )
        ]
    )
    sid, cands = extract_candidates(
        store, _skills(tmp_path), str(doc), WorkType.report, FakeLLM(ex)  # type: ignore[arg-type]
    )
    assert isinstance(sid, int)
    assert len(cands) == 1
    assert "uchwałę nr 12" in cands[0][1]


@respx.mock
def test_extract_candidates_from_doi(tmp_path: Path):
    respx.get("https://api.openalex.org/works/doi:10.1/x").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "Praca",
                "type": "article",
                "abstract_inverted_index": {"dokładność": [0], "92%": [1]},
            },
        )
    )
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(statement="wynik", kind="direct", quotes=["dokładność 92%"])
        ]
    )
    sid, cands = extract_candidates_from_doi(
        store, _skills(tmp_path), "10.1/x", WorkType.article, FakeLLM(ex)  # type: ignore[arg-type]
    )
    assert isinstance(sid, int) and len(cands) == 1


def test_extract_candidates_from_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "imeto.ingest.sources.fetch_url_text",
        lambda url: "Wyniki wpłynęły na politykę edukacyjną.",
    )
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(
                statement="wpływ", kind="direct", quotes=["wpłynęły na politykę"]
            )
        ]
    )
    sid, cands = extract_candidates_from_url(
        store, _skills(tmp_path), "https://gov.pl/r", WorkType.report, FakeLLM(ex)  # type: ignore[arg-type]
    )
    assert isinstance(sid, int) and len(cands) == 1


def test_argue_over_accepted_facts(tmp_path: Path):
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="d", full_text="Wdrożono system X."))
    e = store.add_evidence(sid, "Wdrożono system X")
    c = store.add_claim(sid, "Wdrożono system X.", "direct", [e])
    store.accept_claim(c)

    arg = Argumentation(
        arguments=[ProposedArgument(side="za", statement="wpływ", based_on=[1])]
    )
    out = argue_candidates(store, _skills(tmp_path), sid, FakeLLM(arg))  # type: ignore[arg-type]
    assert len(out) == 1
    assert "[ZA]" in out[0][1]

    acc, rej = apply_argument_decisions(store, [out[0][0]], [out[0][0]])
    assert (acc, rej) == (1, 0)
    assert store.get_argument(out[0][0]).status == "accepted"


def test_corroborate_facts_display(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    hit = [SearchResult("t", "https://gov.pl/x", "s")]
    monkeypatch.setattr(C, "web_search", lambda q, max_results=3: hit)
    monkeypatch.setattr(C, "fetch_url_text", lambda url: "Pilotaż wdrożono oficjalnie.")
    store = ProvenanceStore()
    src = Source(local_identifier="doc", full_text="Opublikowano pilotaż.")
    sid = store.add_source(src)
    e = store.add_evidence(sid, "Opublikowano pilotaż")
    c = store.add_claim(sid, "Opublikowano pilotaż.", "direct", [e])
    store.accept_claim(c)

    md = corroborate_facts(
        store,
        _skills(tmp_path),
        sid,
        FakeLLM(Corroboration(confirms=True, quote="Pilotaż wdrożono oficjalnie")),  # type: ignore[arg-type]
    )
    assert "gov.pl/x" in md and "Pilotaż wdrożono" in md


def test_apply_decisions_accepts_selected_rejects_rest():
    store = ProvenanceStore()
    src = Source(local_identifier="d", full_text="uchwałę nr 12 i tekst")
    sid = store.add_source(src)
    e1 = store.add_evidence(sid, "uchwałę nr 12")
    e2 = store.add_evidence(sid, "tekst")
    c1 = store.add_claim(sid, "a", "direct", [e1])
    c2 = store.add_claim(sid, "b", "direct", [e2])

    acc, rej = apply_decisions(store, [c1, c2], [c1])

    assert (acc, rej) == (1, 1)
    assert store.get_claim(c1).status == "accepted"
    assert store.get_claim(c2).status == "rejected"
