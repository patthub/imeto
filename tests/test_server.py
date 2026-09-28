import json
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from imeto.core.provenance import ProvenanceStore
from imeto.core.schemas import ExtractedFact, Extraction
from imeto.registries.skills import SkillRegistry
from imeto.ui.server import create_app


class FakeLLM:
    model = "fake"

    def structured(self, system: str, user: str, schema: type) -> object:
        fact = ExtractedFact(
            statement="The council adopted the budget.",
            kind="direct",
            quotes=["resolution no. 12"],
        )
        return Extraction(facts=[fact])


def _client(tmp_path: Path, store: ProvenanceStore) -> TestClient:
    skill = tmp_path / "knowledge" / "extraction" / "report"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("## Role\ntest", encoding="utf-8")
    web = tmp_path / "dist"
    web.mkdir()
    (web / "index.html").write_text("<div id=root></div>")
    api = create_app(
        store,
        SkillRegistry(tmp_path / "knowledge"),
        lambda base_url, model: FakeLLM(),  # type: ignore[arg-type,return-value]
        tmp_path / "uploads",
        web,
    )
    return TestClient(api)


def _events(text: str) -> list[dict[str, str]]:
    return [json.loads(line) for line in text.splitlines()]


def test_gui_flow_upload_extract_gate_export(tmp_path: Path):
    doc = Document()
    doc.add_paragraph("The council adopted resolution no. 12 regarding the budget.")
    path = tmp_path / "report.docx"
    doc.save(str(path))
    store = ProvenanceStore()
    client = _client(tmp_path, store)

    with path.open("rb") as f:
        r = client.post(
            "/api/sources",
            data={"mode": "File", "work_type": "report"},
            files={"file": ("report.docx", f)},
        )
    sid = r.json()["id"]
    item = client.get("/api/sources").json()[0]
    assert (item["id"], item["title"], item["facts"]) == (sid, "report.docx", 0)

    events = _events(client.post(f"/api/sources/{sid}/run/extract", json={}).text)
    assert "error" not in events[-1] and "Extracted 1 facts" in events[-1]["log"]

    fact = client.get(f"/api/sources/{sid}").json()["facts"][0]
    assert fact["status"] == "candidate"
    assert fact["grounds"][0]["quote"] == "resolution no. 12"
    assert fact["grounds"][0]["before"] == "The council adopted"  # quote in context

    body = {"accepted": True, "query": "budget resolution 12"}
    client.patch(f"/api/claims/{fact['id']}", json=body)
    fact = client.get(f"/api/sources/{sid}").json()["facts"][0]
    assert fact["status"] == "accepted" and fact["query"] == "budget resolution 12"
    item = client.get("/api/sources").json()[0]  # dashboard counts follow the gate
    assert (item["facts"], item["accepted"], item["queries"]) == (1, 1, 1)

    # a re-run supersedes the first run's facts — the page shows one set, not two
    client.post(f"/api/sources/{sid}/run/extract", json={})
    assert len(client.get(f"/api/sources/{sid}").json()["facts"]) == 1

    csv = client.get(f"/api/sources/{sid}/facts.csv").content.decode("utf-8-sig")
    assert "resolution no. 12" in csv
    assert client.get(f"/sources/{sid}").text == "<div id=root></div>"  # SPA route


def test_errors_arrive_as_events_not_500(tmp_path: Path):
    store = ProvenanceStore()
    client = _client(tmp_path, store)
    r = client.post("/api/sources", data={"mode": "DOI", "doi": " "})
    assert r.status_code == 400
    assert client.post("/api/sources/99/run/extract", json={}).status_code == 404
