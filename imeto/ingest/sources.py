"""Pozyskanie źródła do bazy — z pliku lokalnego albo z API (FetchedWork).
Zwraca `(source_id, created)`; import jest idempotentny po `local_identifier`
(§6.4) — powtórny import tego samego źródła nie tworzy duplikatu."""

from pathlib import Path

from imeto.core.provenance import ProvenanceStore, Source
from imeto.ingest.loaders import FetchedWork
from imeto.ingest.parsing import parse_document
from imeto.worktypes import FABIO, WorkType


def source_from_file(
    store: ProvenanceStore, path: str | Path, work_type: WorkType
) -> tuple[int, bool]:
    local_id = str(path)
    existing = store.source_by_local_identifier(local_id)
    if existing is not None:
        assert existing.id is not None
        return existing.id, False
    text = parse_document(path)
    sid = store.add_source(
        Source(local_identifier=local_id, full_text=text, fabio_type=FABIO[work_type])
    )
    return sid, True


def source_from_fetched(
    store: ProvenanceStore, fetched: FetchedWork
) -> tuple[int, bool]:
    existing = store.source_by_local_identifier(fetched.local_identifier)
    if existing is not None:
        assert existing.id is not None
        return existing.id, False
    sid = store.add_source(
        Source(
            local_identifier=fetched.local_identifier,
            full_text=fetched.full_text,
            fabio_type=fetched.fabio_type,
            title=fetched.title,
            language=fetched.language,
            identifiers=fetched.identifiers,
        )
    )
    return sid, True
