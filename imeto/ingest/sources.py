"""Pozyskanie źródła do bazy — z pliku lokalnego albo z API (FetchedWork).
Zwraca `source_id`, na którym operuje potem `ExtractPhase`."""

from pathlib import Path

from imeto.core.provenance import ProvenanceStore, Source
from imeto.ingest.loaders import FetchedWork
from imeto.ingest.parsing import parse_document
from imeto.worktypes import FABIO, WorkType


def source_from_file(
    store: ProvenanceStore, path: str | Path, work_type: WorkType
) -> int:
    text = parse_document(path)
    return store.add_source(
        Source(
            local_identifier=str(path),
            full_text=text,
            fabio_type=FABIO[work_type],
        )
    )


def source_from_fetched(store: ProvenanceStore, fetched: FetchedWork) -> int:
    return store.add_source(
        Source(
            local_identifier=fetched.local_identifier,
            full_text=fetched.full_text,
            fabio_type=fetched.fabio_type,
            title=fetched.title,
            language=fetched.language,
            identifiers=fetched.identifiers,
        )
    )
