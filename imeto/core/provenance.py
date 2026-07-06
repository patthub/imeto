"""Warstwa trwała provenance. Cały dostęp do bazy idzie przez `ProvenanceStore`
(§9.1) — żaden inny moduł nie dotyka SQL, co czyni silnik wymiennym (SQLite→Postgres).

Model faktu (ustalona zasada POC-2 — nie zlewamy cytowanego z wywnioskowanym):
- `Claim` — fakt (twierdzenie) z rodzajem `kind`: "direct" (napisane wprost) lub
  "inferred" (wywnioskowane). To on przechodzi przez próg człowieka.
- `Evidence` — dosłownie zakotwiczony grunt (oa:Annotation, prov:wasQuotedFrom source).
- `ClaimEvidence` — powiązanie N:M: fakt `prov:wasDerivedFrom` swoje grunty. Fakt może
  opierać się na wielu gruntach (rozproszony), a grunt służyć wielu faktom.

Schemat aligned ze standardami: PROV-O (kolumny), FaBiO (typ źródła), DCTerms, SKG-IF
(identyfikatory), Web Annotation (kotwica cytatu).

Niezmiennik (SAD §8.2): grunt (`Evidence`) powstaje dopiero po weryfikacji spanu przez
`core.span`. Fakt bez ani jednego zweryfikowanego gruntu nie może zaistnieć."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

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
    """Dosłownie zakotwiczony grunt. prov:Entity + oa:Annotation."""

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    quote: str  # oa:TextQuoteSelector.exact (prov:wasQuotedFrom source)
    start: int  # oa:TextPositionSelector.start
    end: int  # oa:TextPositionSelector.end
    generated_at_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    generated_by_activity: str | None = None  # prov:wasGeneratedBy
    attributed_to_agent: str | None = None  # prov:wasAttributedTo / oa:annotatedBy


class Claim(SQLModel, table=True):
    """Fakt. prov:Entity, prov:wasDerivedFrom swoich gruntów (przez ClaimEvidence)."""

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    statement: str
    kind: str  # "direct" (wprost) | "inferred" (wywnioskowane) — NIE zlewać
    generated_at_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    generated_by_activity: str | None = None  # prov:wasGeneratedBy
    attributed_to_agent: str | None = None  # prov:wasAttributedTo (model)
    # Próg człowieka (human-in-the-loop) — decyzja dotyczy FAKTU, nie cytatu.
    status: str = "candidate"  # candidate | accepted | rejected
    approved_by: str | None = None  # prov:wasAttributedTo Person / wasInvalidatedBy
    decided_at: datetime | None = None


class ClaimEvidence(SQLModel, table=True):
    """Powiązanie N:M fakt↔grunt (prov:wasDerivedFrom)."""

    claim_id: int = Field(foreign_key="claim.id", primary_key=True)
    evidence_id: int = Field(foreign_key="evidence.id", primary_key=True)


class SpanNotVerified(ValueError):
    """Cytat nie występuje dosłownie w źródle — grunt odrzucony (SAD §8.2)."""


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

    # --- źródła ---

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

    def source_by_local_identifier(self, local_identifier: str) -> Source | None:
        with Session(self.engine) as s:
            return s.exec(
                select(Source).where(Source.local_identifier == local_identifier)
            ).first()

    # --- grunty (dosłowne kotwice) ---

    def add_evidence(
        self,
        source_id: int,
        quote: str,
        *,
        activity: str | None = None,
        agent: str | None = None,
    ) -> int:
        """Zapisuje grunt tylko gdy cytat weryfikuje się w źródle; inaczej błąd."""
        with Session(self.engine) as s:
            src = s.get(Source, source_id)
            if src is None:
                raise ValueError(f"nieznane source_id={source_id}")
            span = find_span(src.full_text, quote)
            if span is None:
                raise SpanNotVerified(quote)
            ev = Evidence(
                source_id=source_id,
                quote=quote,
                start=span[0],
                end=span[1],
                generated_by_activity=activity,
                attributed_to_agent=agent,
            )
            s.add(ev)
            s.commit()
            s.refresh(ev)
            assert ev.id is not None
            return ev.id

    def get_evidence(self, ev_id: int) -> Evidence:
        with Session(self.engine) as s:
            ev = s.get(Evidence, ev_id)
            if ev is None:
                raise ValueError(f"nieznane ev_id={ev_id}")
            return ev

    def evidence_for_source(self, source_id: int) -> list[Evidence]:
        with Session(self.engine) as s:
            return list(
                s.exec(select(Evidence).where(Evidence.source_id == source_id))
            )

    def evidence_for_claim(self, claim_id: int) -> list[Evidence]:
        stmt = (
            select(Evidence)
            .join(ClaimEvidence, ClaimEvidence.evidence_id == Evidence.id)  # type: ignore[arg-type]
            .where(ClaimEvidence.claim_id == claim_id)
        )
        with Session(self.engine) as s:
            return list(s.exec(stmt))

    # --- fakty ---

    def add_claim(
        self,
        source_id: int,
        statement: str,
        kind: str,
        evidence_ids: list[int],
        *,
        activity: str | None = None,
        agent: str | None = None,
    ) -> int:
        """Tworzy fakt powiązany ze swoimi gruntami. Wymaga >=1 gruntu (zasada:
        fakt bez zweryfikowanego pokrycia nie istnieje)."""
        if not evidence_ids:
            raise ValueError("fakt musi mieć co najmniej jeden zweryfikowany grunt")
        with Session(self.engine) as s:
            claim = Claim(
                source_id=source_id,
                statement=statement,
                kind=kind,
                generated_by_activity=activity,
                attributed_to_agent=agent,
            )
            s.add(claim)
            s.commit()
            s.refresh(claim)
            assert claim.id is not None
            for eid in evidence_ids:
                s.add(ClaimEvidence(claim_id=claim.id, evidence_id=eid))
            s.commit()
            return claim.id

    def get_claim(self, claim_id: int) -> Claim:
        with Session(self.engine) as s:
            claim = s.get(Claim, claim_id)
            if claim is None:
                raise ValueError(f"nieznane claim_id={claim_id}")
            return claim

    def claims_for_source(
        self, source_id: int, status: str | None = None
    ) -> list[Claim]:
        stmt = select(Claim).where(Claim.source_id == source_id)
        if status is not None:
            stmt = stmt.where(Claim.status == status)
        with Session(self.engine) as s:
            return list(s.exec(stmt))

    # --- próg człowieka (na fakcie) ---

    def _decide(self, claim_id: int, status: str, by: str | None) -> None:
        with Session(self.engine) as s:
            claim = s.get(Claim, claim_id)
            if claim is None:
                raise ValueError(f"nieznane claim_id={claim_id}")
            claim.status = status
            claim.approved_by = by
            claim.decided_at = datetime.now(UTC)
            s.add(claim)
            s.commit()

    def accept_claim(self, claim_id: int, by: str | None = None) -> None:
        """Próg: człowiek akceptuje fakt (prov:wasAttributedTo Person)."""
        self._decide(claim_id, "accepted", by)

    def reject_claim(self, claim_id: int, by: str | None = None) -> None:
        """Próg: człowiek odrzuca fakt (prov:wasInvalidatedBy)."""
        self._decide(claim_id, "rejected", by)

    # --- audyt ---

    def verify_span(self, source_id: int, ev_id: int) -> bool:
        """Audyt (I-audit): przelicza span zapisanego gruntu względem źródła."""
        with Session(self.engine) as s:
            src = s.get(Source, source_id)
            ev = s.get(Evidence, ev_id)
            if src is None or ev is None:
                return False
            return find_span(src.full_text, ev.quote) == (ev.start, ev.end)
