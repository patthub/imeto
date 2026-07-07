from pathlib import Path

import httpx
import respx
from docx import Document

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.registries.skills import SkillRegistry
from imeto.ui.app import (
    apply_decisions,
    extract_candidates,
    extract_candidates_from_doi,
)
from imeto.worktypes import WorkType


class FakeLLM:
    model = "fake"

    def __init__(self, ex: Extraction) -> None:
        self._ex = ex

    def structured(
        self, system: str, user: str, schema: type[Extraction]
    ) -> Extraction:
        return self._ex


def _make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("Rada gminy przyjęła uchwałę nr 12 w sprawie budżetu.")
    doc.save(str(path))
    return path


def _skills(tmp_path: Path) -> SkillRegistry:
    base = tmp_path / "knowledge" / "extraction"
    for name in ("report", "article"):
        d = base / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("## Rola\nskill testowy", encoding="utf-8")
    return SkillRegistry(tmp_path / "knowledge")


def test_extract_candidates_returns_labeled_ids(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx")
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(
                statement="Rada przyjęła.", kind="direct", quotes=["uchwałę nr 12"]
            ),
            ExtractedFact(
                statement="Dotyczyło budżetu.",
                kind="inferred",
                quotes=["w sprawie budżetu"],
            ),
        ]
    )
    cands = extract_candidates(
        store, _skills(tmp_path), str(doc), WorkType.report, FakeLLM(ex)  # type: ignore[arg-type]
    )
    assert len(cands) == 2
    assert all(isinstance(cid, int) for cid, _ in cands)
    labels = " ".join(label for _, label in cands)
    assert "(direct)" in labels and "(inferred)" in labels
    assert "uchwałę nr 12" in labels


@respx.mock
def test_extract_candidates_from_doi(tmp_path: Path):
    respx.get("https://api.openalex.org/works/doi:10.1/x").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "Praca",
                "type": "article",
                "abstract_inverted_index": {
                    "Model": [0], "osiągnął": [1], "dokładność": [2], "92%": [3]
                },
            },
        )
    )
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(statement="wynik", kind="direct", quotes=["dokładność 92%"])
        ]
    )
    cands = extract_candidates_from_doi(
        store, _skills(tmp_path), "10.1/x", WorkType.article, FakeLLM(ex)  # type: ignore[arg-type]
    )
    assert len(cands) == 1
    assert "(direct)" in cands[0][1]
    assert "dokładność 92%" in cands[0][1]


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
    assert store.get_claim(c1).approved_by == "operator"
