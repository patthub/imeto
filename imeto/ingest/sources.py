"""Ingesting a source into the store — from a local file or an API (FetchedWork).
Returns `(source_id, created)`; import is idempotent on `local_identifier`
(§6.4) — re-importing the same source creates no duplicate."""

from pathlib import Path

from imeto.core.provenance import ProvenanceStore, Source
from imeto.ingest.loaders import FetchedWork
from imeto.ingest.parsing import parse_document
from imeto.ingest.web import fetch_url_text
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


FABIO_WEBPAGE = "http://purl.org/spar/fabio/WebPage"


def source_from_text(
    store: ProvenanceStore,
    identifier: str,
    text: str,
    fabio_type: str = FABIO_WEBPAGE,
) -> tuple[int, bool]:
    """Stores a source from ALREADY-fetched text (e.g. an evidence page during
    corroboration, without re-fetching). Idempotent on the identifier."""
    existing = store.source_by_local_identifier(identifier)
    if existing is not None:
        assert existing.id is not None
        return existing.id, False
    sid = store.add_source(
        Source(local_identifier=identifier, full_text=text, fabio_type=fabio_type)
    )
    return sid, True


def source_from_url(
    store: ProvenanceStore, url: str, work_type: WorkType
) -> tuple[int, bool]:
    """Fetches a web page (impact evidence), stores it as a source. Idempotent."""
    existing = store.source_by_local_identifier(url)
    if existing is not None:
        assert existing.id is not None
        return existing.id, False
    text = fetch_url_text(url)
    if not text:
        raise ValueError(f"could not fetch text from {url}")
    sid = store.add_source(
        Source(local_identifier=url, full_text=text, fabio_type=FABIO[work_type])
    )
    return sid, True


def source_from_fetched(
    store: ProvenanceStore, fetched: FetchedWork
) -> tuple[int, bool]:
    existing = store.source_by_local_identifier(fetched.local_identifier)
    if existing is not None:
        assert existing.id is not None
        if fetched.signals:  # re-import refreshes the stale-prone metrics
            store.set_signals(existing.id, fetched.signals)
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
    if fetched.signals:
        store.set_signals(sid, fetched.signals)
    return sid, True
