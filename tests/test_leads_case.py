"""Impact leads → reach, pinned candidates, case building, old-DB upgrade. No network,
no model."""

import sqlite3
from pathlib import Path

import httpx
import pytest
import respx

from imeto.core.provenance import ProvenanceStore, Source
from imeto.phases.corroborate import citations_for
from imeto.tools.signals import case_links, work_reach
from imeto.ui.app import set_argument_sphere


def test_old_database_gains_new_nullable_columns(tmp_path: Path):
    db = tmp_path / "old.db"
    ProvenanceStore(f"sqlite:///{db}")
    with sqlite3.connect(db) as conn:  # simulate a DB from before `sphere` existed
        conn.execute("ALTER TABLE argument DROP COLUMN sphere")
    store = ProvenanceStore(f"sqlite:///{db}")  # must not crash, must add it back
    sid = store.add_source(Source(local_identifier="x", full_text="t"))
    aid = store.add_argument(sid, "k", "gap", "no data", [], sphere="culture")
    assert store.get_argument(aid).sphere == "culture"


def test_pinned_candidates_go_first_and_survive_a_metrics_refresh():
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="report.pdf", full_text="t"))
    cand = {"title": "NBP paper", "url": "https://nbp.pl/a.pdf", "snippet": "pinned"}
    store.pin_candidate(sid, cand)
    store.pin_candidate(sid, cand)  # idempotent
    store.set_signals(sid, {"cited_by": 3})  # a refresh must not drop the pin
    src = store.get_source(sid)
    assert [c.url for c in citations_for(src, store)] == ["https://nbp.pl/a.pdf"]
    assert store.get_signals(sid) == {"pinned": [cand], "cited_by": 3}


def test_sphere_is_validated():
    store = ProvenanceStore()
    sid = store.add_source(Source(local_identifier="x", full_text="t"))
    aid = store.add_argument(sid, "k", "gap", "g", [])
    with pytest.raises(ValueError):
        set_argument_sphere(store, aid, "astrology")
    set_argument_sphere(store, aid, "")  # clears
    assert store.get_argument(aid).sphere is None


@respx.mock
def test_work_reach_counts_countries_and_fields():
    respx.get("https://api.openalex.org/works").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "meta": {"count": 12},
                    "group_by": [
                        {
                            "key": "https://openalex.org/countries/PL",
                            "key_display_name": "Poland",
                            "count": 7,
                        },
                        {"key": "unknown", "key_display_name": "unknown", "count": 2},
                    ],
                },
            ),
            httpx.Response(
                200,
                json={
                    "group_by": [
                        {
                            "key": "https://openalex.org/fields/33",
                            "key_display_name": "Social Sciences",
                            "count": 9,
                        }
                    ]
                },
            ),
        ]
    )
    r = work_reach("W1")
    assert r["citing"] == 12
    assert r["countries"] == [{"code": "PL", "name": "Poland", "works": 7}]
    assert r["fields"][0]["name"] == "Social Sciences"


@respx.mock
def test_case_links_finds_which_of_our_works_the_lead_cites():
    respx.get("https://api.openalex.org/works/W9").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "https://openalex.org/W9",
                "title": "Inflation report",
                "publication_year": 2025,
                "best_oa_location": {"pdf_url": "https://nbp.pl/r.pdf"},
                "primary_location": {"source": {"display_name": "Materiały i Studia"}},
                "referenced_works": [
                    "https://openalex.org/W1",  # ours
                    "https://openalex.org/W5",  # someone else's
                ],
            },
        )
    )
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "doi": "https://doi.org/10.1/a",
                        "title": "Ours",
                    }
                ]
            },
        )
    )
    links = case_links("W9", {"W1", "W2"}, via="National Bank of Poland")
    assert links["ours"] == [
        {"id": "W1", "doi": "https://doi.org/10.1/a", "title": "Ours"}
    ]
    assert links["candidate"]["url"] == "https://nbp.pl/r.pdf"
    assert "National Bank of Poland" in links["candidate"]["snippet"]
