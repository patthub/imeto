from pathlib import Path

from docx import Document

from imeto.core.provenance import ProvenanceStore
from imeto.ingest.loaders import FetchedWork
from imeto.ingest.sources import source_from_fetched, source_from_file
from imeto.worktypes import WorkType


def test_source_from_file_sets_fabio(tmp_path: Path):
    p = tmp_path / "s.docx"
    doc = Document()
    doc.add_paragraph("Przeszkolono 45 osób.")
    doc.save(str(p))

    store = ProvenanceStore()
    sid = source_from_file(store, p, WorkType.report)
    src = store.get_source(sid)
    assert "Przeszkolono 45 osób" in src.full_text
    assert src.fabio_type.endswith("Report")


def test_source_from_fetched_carries_metadata():
    store = ProvenanceStore()
    fetched = FetchedWork(
        local_identifier="https://doi.org/10.1/x",
        title="Tytuł",
        full_text="Abstrakt pracy.",
        fabio_type="http://purl.org/spar/fabio/JournalArticle",
        language="pl",
        identifiers=[{"scheme": "doi", "value": "10.1/x"}],
        work_type=WorkType.article,
    )
    sid = source_from_fetched(store, fetched)
    src = store.get_source(sid)
    assert src.local_identifier == "https://doi.org/10.1/x"
    assert src.full_text == "Abstrakt pracy."
    assert src.title == "Tytuł"
    assert src.identifiers == [{"scheme": "doi", "value": "10.1/x"}]
