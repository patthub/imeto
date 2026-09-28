import httpx
import pytest
import respx

from imeto.core.provenance import ProvenanceStore
from imeto.ingest.loaders import FetchedWork, RateLimited, _get, work_signals
from imeto.ingest.sources import source_from_fetched
from imeto.tools.signals import is_non_academic, partners, scope_filter
from imeto.ui.app import check_entity


def test_work_signals_keeps_only_raw_context():
    s = work_signals(
        {
            "fwci": 3.76,  # dropped: normalized metrics mislead for SSH
            "cited_by_count": 31,
            "primary_topic": {"display_name": "T", "field": {"display_name": "F"}},
        }
    )
    assert s == {"openalex_id": None, "cited_by": 31, "topic": "T", "field": "F"}
    assert work_signals({})["field"] is None  # sparse record → no crash


def test_partner_filter_drops_academies_mislabeled_as_government():
    assert is_non_academic({"type": "nonprofit", "display_name": "PISM"})
    assert is_non_academic({"type": "archive", "display_name": "National Museum"})
    assert not is_non_academic(
        {"type": "government", "display_name": "Polish Academy of Sciences"}
    )
    assert not is_non_academic(
        {"type": "other", "display_name": "Harvard University Press"}
    )
    assert not is_non_academic({"type": "education", "display_name": "SWPS"})
    # public research bodies typed "government" by OpenAlex
    for name in ("Inserm", "Institut National de Recherche pour l'Agriculture"):
        assert not is_non_academic({"type": "government", "display_name": name})
    # … but "research" alone must not drop a think tank
    assert is_non_academic(
        {"type": "nonprofit", "display_name": "Center for Social and Economic Research"}
    )


def test_signals_stored_on_import_and_refreshed_on_reimport():
    store = ProvenanceStore()
    fw = FetchedWork(
        local_identifier="https://doi.org/10.1/x",
        title="t",
        full_text="abstract",
        fabio_type="x",
        language="en",
        signals={"fwci": 1.2},
    )
    sid, _ = source_from_fetched(store, fw)
    assert store.get_signals(sid) == {"fwci": 1.2}
    fw.signals = {"fwci": 2.5}
    assert source_from_fetched(store, fw) == (sid, False)
    assert store.get_signals(sid) == {"fwci": 2.5}


@respx.mock
def test_get_retries_openalex_throttling(monkeypatch):
    monkeypatch.setattr("imeto.ingest.loaders.time.sleep", lambda _s: None)
    route = respx.get("https://api.openalex.org/works").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    assert _get("https://api.openalex.org/works", params=None, client=None) == {
        "ok": True
    }
    assert route.call_count == 2


def test_scope_filter_switches_between_institution_and_researcher():
    assert scope_filter("I1", "2021-2026").startswith("authorships.institutions.id:I1,")
    assert scope_filter("A7", "2021-2026").startswith("authorships.author.id:A7,")
    assert "primary_topic.domain.id:2" in scope_filter("I1")  # SSH only


def test_entity_id_is_validated_before_it_reaches_a_filter():
    assert check_entity("I4654613") == "I4654613"
    for bad in ("I1,type:report", "W123", "I", "i1"):
        with pytest.raises(ValueError):
            check_entity(bad)


@respx.mock
def test_partners_pages_through_all_groups_and_drops_academics():
    respx.get("https://api.openalex.org/works").mock(
        side_effect=[  # two cursor pages — nothing is cut at 200
            httpx.Response(
                200,
                json={
                    "meta": {"next_cursor": "c2"},
                    "group_by": [
                        {"key": "https://openalex.org/I9", "count": 50},  # ourselves
                        {"key": "https://openalex.org/I1", "count": 7},
                    ],
                },
            ),
            httpx.Response(
                200,
                json={
                    "meta": {"next_cursor": None},
                    "group_by": [{"key": "https://openalex.org/I2", "count": 3}],
                },
            ),
        ]
    )
    respx.get("https://api.openalex.org/institutions").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/I1",
                        "display_name": "PISM",
                        "type": "nonprofit",
                        "country_code": "PL",
                    },
                    {
                        "id": "https://openalex.org/I2",
                        "display_name": "Inserm",
                        "type": "government",
                        "country_code": "FR",
                    },
                ]
            },
        )
    )
    rows = partners("I9")
    assert [(r["name"], r["works_count"]) for r in rows] == [("PISM", 7)]


def test_bad_entity_is_a_400_not_an_openalex_call(tmp_path):
    from tests.test_server import _client

    r = _client(tmp_path, ProvenanceStore()).get("/api/leads/I1,type:x/partners")
    assert r.status_code == 400


@respx.mock
def test_get_fails_fast_when_the_daily_budget_is_spent(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("imeto.ingest.loaders.time.sleep", slept.append)
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "57210"})
    )
    with pytest.raises(RateLimited, match="daily limit"):
        _get("https://api.openalex.org/works", params=None, client=None)
    assert slept == []  # never waits hours
