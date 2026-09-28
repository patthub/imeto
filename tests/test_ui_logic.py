from pathlib import Path

import httpx
import pytest
import respx
from docx import Document

from imeto.core.provenance import ProvenanceStore, Source
from imeto.core.schemas import (
    Argumentation,
    ExtractedFact,
    Extraction,
    ProposedArgument,
)
from imeto.registries.skills import SkillRegistry
from imeto.ui.app import (
    argue_candidates,
    extract_candidates,
    extract_candidates_from_doi,
    extract_candidates_from_url,
    facts_csv,
    facts_rows,
    load_source,
    save_query,
    set_accepted,
    set_argument_accepted,
)
from imeto.worktypes import WorkType


def test_facts_rows_shows_provenance_and_external_mark():
    # table: provenance + context; internal fact without a lead → "—" (marked)
    store = ProvenanceStore()
    sid = store.add_source(
        Source(
            local_identifier="doc",
            full_text="Intro. System X was deployed in the municipality. End.",
        )
    )
    e = store.add_evidence(sid, "System X was deployed")
    c = store.add_claim(sid, "System X was deployed.", "direct", [e])
    ext = store.add_source(
        Source(
            local_identifier="https://gov.pl/p", full_text="X has worked since 2025."
        )
    )
    ee = store.add_evidence(ext, "X has worked since 2025")
    c2 = store.add_claim(
        sid, "Internal fact.", "direct", [store.add_evidence(sid, "Intro")]
    )

    rows = facts_rows(store, [c, c2])

    assert rows[0][1] == "direct" and "System X was deployed" in rows[0][2]
    assert "System X was deployed" in rows[0][3]  # quote in source
    assert "–" in rows[0][4]  # start–end position
    assert "municipality" in rows[0][5]  # context around the quote
    assert rows[0][6] == "—"  # trail: suggester didn't run → no lead
    assert rows[1][7] == "—"  # impact: no external corroboration (marked)
    store.link_evidence(c, ee)
    assert "gov.pl" in facts_rows(store, [c])[0][7]  # after linking — impact visible

    # CSV: headers + fact row, readable in Excel (BOM)
    text = Path(facts_csv(store, [c])).read_text(encoding="utf-8-sig")
    assert "Fact" in text and "System X was deployed" in text


def test_fact_card_edits_write_straight_to_the_store():
    # the card owns the fact: the checkbox is the gate, the textbox is the query
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="doc", full_text="A deployed. B."))
    c1 = store.add_claim(sid, "A deployed.", "direct", [store.add_evidence(sid, "A")])
    c2 = store.add_claim(sid, "B.", "direct", [store.add_evidence(sid, "B")])
    store.upsert_lead(c1, "look for deployment", "deployment X municipality")

    set_accepted(store, c1, True)
    set_accepted(store, c2, False)
    assert store.get_claim(c1).status == "accepted"
    assert store.get_claim(c2).status == "rejected"

    assert save_query(store, c1, "deployment X Mazovia 2025") is True  # human rewrites
    lead1 = store.get_lead(c1)
    assert lead1 is not None and lead1.query == "deployment X Mazovia 2025"
    assert lead1.lead == "look for deployment"  # edit touches the query only

    assert save_query(store, c2, "B in the press") is True  # model gave none
    lead2 = store.get_lead(c2)
    assert lead2 is not None and lead2.query == "B in the press"

    assert save_query(store, c1, "  ") is False  # emptied → lead cleared
    assert store.get_lead(c1) is None


class FakeLLM:
    model = "fake"

    def __init__(self, ex: object) -> None:
        self._ex = ex

    def structured(self, system: str, user: str, schema: type) -> object:
        return self._ex


def _make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("The council adopted resolution no. 12 regarding the budget.")
    doc.save(str(path))
    return path


def _skills(tmp_path: Path) -> SkillRegistry:
    base = tmp_path / "knowledge"
    for sub, name in [("extraction", "report"), ("extraction", "article")]:
        d = base / sub / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("## Role\ntest", encoding="utf-8")
    crit = base / "criteria" / "kryterium_iii"
    crit.mkdir(parents=True)
    (crit / "SKILL.md").write_text("## Rubric\ntest", encoding="utf-8")
    return SkillRegistry(base)


def test_load_source_creates_source_without_extracting(tmp_path: Path):
    # load = fetch/create source + preview, NO extraction (no claims yet)
    doc = _make_docx(tmp_path / "s.docx")
    store = ProvenanceStore()
    sid = load_source(store, "File", str(doc), "", "", WorkType.report)
    assert isinstance(sid, int)
    assert store.claims_for_source(sid) == []  # nothing extracted on load


def test_extract_candidates_returns_source_and_labels(tmp_path: Path):
    doc = _make_docx(tmp_path / "s.docx")
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(
                statement="The council adopted.",
                kind="direct",
                quotes=["resolution no. 12"],
            )
        ]
    )
    sid, cands = extract_candidates(
        store,
        _skills(tmp_path),
        str(doc),
        WorkType.report,
        FakeLLM(ex),  # type: ignore[arg-type]
    )
    assert isinstance(sid, int)
    assert len(cands) == 1
    assert "resolution no. 12" in cands[0][1]


@respx.mock
def test_extract_candidates_from_doi(tmp_path: Path):
    respx.get("https://api.openalex.org/works/doi:10.1/x").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "Work",
                "type": "article",
                "abstract_inverted_index": {"accuracy": [0], "92%": [1]},
            },
        )
    )
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(statement="result", kind="direct", quotes=["accuracy 92%"])
        ]
    )
    sid, cands = extract_candidates_from_doi(
        store,
        _skills(tmp_path),
        "10.1/x",
        WorkType.article,
        FakeLLM(ex),  # type: ignore[arg-type]
    )
    assert isinstance(sid, int) and len(cands) == 1


def test_extract_candidates_from_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "imeto.ingest.sources.fetch_url_text",
        lambda url: "The results influenced education policy.",
    )
    store = ProvenanceStore()
    ex = Extraction(
        facts=[
            ExtractedFact(
                statement="impact",
                kind="direct",
                quotes=["influenced education policy"],
            )
        ]
    )
    sid, cands = extract_candidates_from_url(
        store,
        _skills(tmp_path),
        "https://gov.pl/r",
        WorkType.report,
        FakeLLM(ex),  # type: ignore[arg-type]
    )
    assert isinstance(sid, int) and len(cands) == 1


def test_argue_over_accepted_facts(tmp_path: Path):
    store = ProvenanceStore()
    sid = store.add_source(
        Source(local_identifier="d", full_text="System X was deployed.")
    )
    e = store.add_evidence(sid, "System X was deployed")
    c = store.add_claim(sid, "System X was deployed.", "direct", [e])
    store.accept_claim(c)

    arg = Argumentation(
        arguments=[ProposedArgument(side="for", statement="impact", based_on=[1])]
    )
    out = argue_candidates(store, _skills(tmp_path), sid, FakeLLM(arg))  # type: ignore[arg-type]
    assert len(out) == 1
    assert "[FOR]" in out[0][1]

    set_argument_accepted(store, out[0][0], True)
    assert store.get_argument(out[0][0]).status == "accepted"
