from pathlib import Path

import pytest
from docx import Document

from imeto.core.provenance import ProvenanceStore
from imeto.ingest import sources
from imeto.ingest.loaders import FetchedWork
from imeto.ingest.sources import source_from_fetched, source_from_file, source_from_url
from imeto.worktypes import WorkType


def test_source_from_file_sets_fabio(tmp_path: Path):
    p = tmp_path / "s.docx"
    doc = Document()
    doc.add_paragraph("Trained 45 people.")
    doc.save(str(p))

    store = ProvenanceStore()
    sid, created = source_from_file(store, p, WorkType.report)
    assert created is True
    src = store.get_source(sid)
    assert "Trained 45 people" in src.full_text
    assert src.fabio_type.endswith("Report")

    # re-importing the same path does not create a duplicate (idempotency §6.4)
    sid2, created2 = source_from_file(store, p, WorkType.report)
    assert (sid2, created2) == (sid, False)


def test_source_from_fetched_carries_metadata():
    store = ProvenanceStore()
    fetched = FetchedWork(
        local_identifier="https://doi.org/10.1/x",
        title="Title",
        full_text="Work abstract.",
        fabio_type="http://purl.org/spar/fabio/JournalArticle",
        language="en",
        identifiers=[{"scheme": "doi", "value": "10.1/x"}],
        work_type=WorkType.article,
    )
    sid, created = source_from_fetched(store, fetched)
    assert created is True
    src = store.get_source(sid)
    assert src.local_identifier == "https://doi.org/10.1/x"
    assert src.full_text == "Work abstract."
    assert src.title == "Title"
    assert src.identifiers == [{"scheme": "doi", "value": "10.1/x"}]


def test_source_from_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sources, "fetch_url_text", lambda url: "The results influenced policy."
    )
    store = ProvenanceStore()
    sid, created = source_from_url(store, "https://gov.pl/raport", WorkType.report)
    assert created is True
    src = store.get_source(sid)
    assert src.local_identifier == "https://gov.pl/raport"
    assert src.full_text.startswith("The results")

    sid2, created2 = source_from_url(store, "https://gov.pl/raport", WorkType.report)
    assert (sid2, created2) == (sid, False)  # idempotent by url
