"""Warstwa trwała provenance. Cały dostęp do bazy idzie przez `ProvenanceStore`
(§9.1) — żaden inny moduł nie dotyka SQL, co czyni silnik wymiennym (SQLite→Postgres).

Schemat jest aligned ze standardami (ustalenia projektowe):
- każda encja to `prov:Entity`; kolumny nazwane terminami PROV-O,
- `Source` typowany klasą FaBiO + pola DCTerms + identyfikatory PID w modelu SKG-IF,
- `Evidence` to `oa:Annotation`: `quote` = oa:TextQuoteSelector.exact
  (prov:wasQuotedFrom source), `start`/`end` = oa:TextPositionSelector.

Niezmiennik (SAD §8.2): `add_evidence` przyjmuje rekord dopiero po weryfikacji spanu
przez `core.span` — logika anty-halucynacji niezależna od silnika bazy."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from imeto.core.schemas import ExtractedFact
from imeto.core.span import find_span

FABIO_REPORT = "http://purl.org/spar/fabio/Report"


class Source(SQLModel, table=True):
    """Dokument źródłowy. prov:Entity, typowany klasą FaBiO."""

    id: int | None = Field(default=None, primary_key=True)
    local_identifier: str = Field(unique=True, index=True)  # SKG-IF; IRI-ready
    fabio_type: str = FABIO_REPORT  # klasa FaBiO (URI)
    title: str | None = None  # dcterms:title
    language: str | None = None  # dcterms:language (ISO 639-1)
    # SKG-IF identifiers[]: lista {scheme, value} (DOI/ORCID/handle...)
    identifiers: list[dict[str, str]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    full_text: str
    # ponytail: content_hash do idempotencji importu (§6.4) dodać w warstwie ingest,
    #           gdy import z pliku stanie się realny — tu niepotrzebny.


class Evidence(SQLModel, table=True):
    """Zweryfikowany, dosłowny cytat kotwiczący fakt w źródle.
    prov:Entity + oa:Annotation (prov:wasQuotedFrom source)."""

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    quote: str  # oa:TextQuoteSelector.exact
    start: int  # oa:TextPositionSelector.start
    end: int  # oa:TextPositionSelector.end
    statement: str  # fakt, który cytat popiera
    # ponytail: statement staje się osobnym Claim(prov:Entity, prov:wasDerivedFrom
    #           evidence) + tabela linkująca w POC-2, gdy claim↔evidence jest N:M.
    # prov:generatedAtTime
    generated_at_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    generated_by_activity: str | None = None  # prov:wasGeneratedBy (id przebiegu fazy)
    attributed_to_agent: str | None = None  # prov:wasAttributedTo / oa:annotatedBy
    # Próg człowieka (human-in-the-loop): kandydat -> zaakceptowany/odrzucony.
    status: str = "candidate"  # candidate | accepted | rejected
    approved_by: str | None = None  # prov:wasAttributedTo Person / wasInvalidatedBy
    decided_at: datetime | None = None


class SpanNotVerified(ValueError):
    """Cytat nie występuje dosłownie w źródle — dowód odrzucony (SAD §8.2)."""


def _enable_fk(engine: Engine) -> None:
    # SQLite egzekwuje klucze obce dopiero po włączeniu, per połączenie (§9.1).
    @event.listens_for(engine, "connect")
    def _set(dbapi_conn: object, _rec: object) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]


class ProvenanceStore:
    def __init__(self, db_url: str = "sqlite://") -> None:
        # StaticPool: jedno połączenie — pasuje do profilu jednego użytkownika i
        # utrzymuje bazę in-memory między sesjami tej instancji (testy bez plików).
        self.engine = create_engine(
            db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        _enable_fk(self.engine)
        SQLModel.metadata.create_all(self.engine)

    def add_source(self, src: Source) -> int:
        with Session(self.engine) as s:
            s.add(src)
            s.commit()
            s.refresh(src)
            assert src.id is not None
            return src.id

    def get_source(self, source_id: int) -> Source:
        with Session(self.engine) as s:
            src = s.get(Source, source_id)
            if src is None:
                raise ValueError(f"nieznane source_id={source_id}")
            return src

    def get_evidence(self, ev_id: int) -> Evidence:
        with Session(self.engine) as s:
            ev = s.get(Evidence, ev_id)
            if ev is None:
                raise ValueError(f"nieznane ev_id={ev_id}")
            return ev

    def add_evidence(
        self,
        source_id: int,
        fact: ExtractedFact,
        *,
        activity: str | None = None,
        agent: str | None = None,
    ) -> int:
        """Zapisuje dowód tylko gdy cytat weryfikuje się w źródle; inaczej błąd."""
        with Session(self.engine) as s:
            src = s.get(Source, source_id)
            if src is None:
                raise ValueError(f"nieznane source_id={source_id}")
            span = find_span(src.full_text, fact.quote)
            if span is None:
                raise SpanNotVerified(fact.quote)
            ev = Evidence(
                source_id=source_id,
                quote=fact.quote,
                start=span[0],
                end=span[1],
                statement=fact.statement,
                generated_by_activity=activity,
                attributed_to_agent=agent,
            )
            s.add(ev)
            s.commit()
            s.refresh(ev)
            assert ev.id is not None
            return ev.id

    def evidence_for_source(
        self, source_id: int, status: str | None = None
    ) -> list[Evidence]:
        stmt = select(Evidence).where(Evidence.source_id == source_id)
        if status is not None:
            stmt = stmt.where(Evidence.status == status)
        with Session(self.engine) as s:
            return list(s.exec(stmt))

    def _decide(self, ev_id: int, status: str, by: str | None) -> None:
        with Session(self.engine) as s:
            ev = s.get(Evidence, ev_id)
            if ev is None:
                raise ValueError(f"nieznane ev_id={ev_id}")
            ev.status = status
            ev.approved_by = by
            ev.decided_at = datetime.now(UTC)
            s.add(ev)
            s.commit()

    def accept_evidence(self, ev_id: int, by: str | None = None) -> None:
        """Próg: człowiek akceptuje kandydata (prov:wasAttributedTo Person)."""
        self._decide(ev_id, "accepted", by)

    def reject_evidence(self, ev_id: int, by: str | None = None) -> None:
        """Próg: człowiek odrzuca kandydata (prov:wasInvalidatedBy)."""
        self._decide(ev_id, "rejected", by)

    def verify_span(self, source_id: int, ev_id: int) -> bool:
        """Audyt (I-audit): przelicza span zapisanego dowodu względem źródła."""
        with Session(self.engine) as s:
            src = s.get(Source, source_id)
            ev = s.get(Evidence, ev_id)
            if src is None or ev is None:
                return False
            return find_span(src.full_text, ev.quote) == (ev.start, ev.end)
