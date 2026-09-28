"""Provenance persistence layer. All DB access goes through `ProvenanceStore`
(§9.1) — no other module touches SQL, which keeps the engine swappable
(SQLite→Postgres).

Fact model (settled POC-2 rule — we don't conflate quoted with inferred):
- `Claim` — a fact (statement) with a `kind`: "direct" (stated explicitly) or
  "inferred" (derived). This is what passes the human gate.
- `Evidence` — a verbatim-anchored ground (oa:Annotation, prov:wasQuotedFrom source).
- `ClaimEvidence` — an N:M link: a fact `prov:wasDerivedFrom` its grounds. A fact may
  rest on many grounds (dispersed), and a ground may serve many facts.

Schema aligned with standards: PROV-O (columns), FaBiO (source type), DCTerms, SKG-IF
(identifiers), Web Annotation (quote anchor).

Invariant (SAD §8.2): a ground (`Evidence`) is created only after span verification
by `core.span`. A fact with no verified ground cannot exist."""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import JSON, Column, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from imeto.core.span import find_span

FABIO_REPORT = "http://purl.org/spar/fabio/Report"


class Source(SQLModel, table=True):
    """Source document. prov:Entity, typed by a FaBiO class."""

    id: int | None = Field(default=None, primary_key=True)
    local_identifier: str = Field(unique=True, index=True)  # SKG-IF; IRI-ready
    fabio_type: str = FABIO_REPORT  # FaBiO class (URI)
    title: str | None = None  # dcterms:title
    language: str | None = None  # dcterms:language (ISO 639-1)
    # SKG-IF identifiers[]: list of {scheme, value} (DOI/ORCID/handle...)
    identifiers: list[dict[str, str]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    full_text: str
    # ponytail: content_hash for import idempotency (§6.4) — add in the ingest
    #           layer once file import becomes real; not needed here.


class SourceSignals(SQLModel, table=True):
    """OpenAlex context of a source — citation count, reach, pinned citing
    candidates — one row per source. Context, never evidence. Its own table: it goes
    stale and gets refreshed, independently of the source text."""

    source_id: int = Field(foreign_key="source.id", primary_key=True)
    data: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Evidence(SQLModel, table=True):
    """Verbatim-anchored ground. prov:Entity + oa:Annotation."""

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    quote: str  # oa:TextQuoteSelector.exact (prov:wasQuotedFrom source)
    start: int  # oa:TextPositionSelector.start
    end: int  # oa:TextPositionSelector.end
    generated_at_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    generated_by_activity: str | None = None  # prov:wasGeneratedBy
    attributed_to_agent: str | None = None  # prov:wasAttributedTo / oa:annotatedBy


class Claim(SQLModel, table=True):
    """Fact. prov:Entity, prov:wasDerivedFrom its grounds (via ClaimEvidence)."""

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    statement: str
    kind: str  # "direct" (explicit) | "inferred" (derived) — do NOT conflate
    # Suggester hint (NOT a gate): whether the fact has an external impact trail
    # to search for. unknown = not yet assessed | internal = no trail (don't
    # search the web) | candidate = worth searching (has a linked Lead). A human
    # may change it.
    external_trail: str = "unknown"
    generated_at_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    generated_by_activity: str | None = None  # prov:wasGeneratedBy
    attributed_to_agent: str | None = None  # prov:wasAttributedTo (model)
    # Human gate (human-in-the-loop) — the decision is about the FACT, not the quote.
    status: str = "candidate"  # candidate | accepted | rejected
    approved_by: str | None = None  # prov:wasAttributedTo Person / wasInvalidatedBy
    decided_at: datetime | None = None


class ClaimEvidence(SQLModel, table=True):
    """N:M link fact↔ground (prov:wasDerivedFrom)."""

    claim_id: int = Field(foreign_key="claim.id", primary_key=True)
    evidence_id: int = Field(foreign_key="evidence.id", primary_key=True)


class Lead(SQLModel, table=True):
    """Impact trail attached to a fact: what to search the web for (`lead`) and
    with what `query`. A CANDIDATE (Z1), not evidence — the query is human-editable
    before searching. One trail per fact (the latest from the suggester). It becomes
    evidence only as a verbatim-anchored confirmation (Evidence) from corroboration."""

    id: int | None = Field(default=None, primary_key=True)
    claim_id: int = Field(foreign_key="claim.id", unique=True, index=True)
    lead: str  # what specifically to search for (impact trail outside science)
    query: str  # search-engine query (editable)


class Argument(SQLModel, table=True):
    """Assessment argument per rubric (FOR/AGAINST/GAP). prov:Entity,
    prov:wasDerivedFrom the facts it rests on (via ArgumentClaim). A structure
    parallel to Claim one level up: an argument rests on facts as a fact rests on
    grounds."""

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    criterion: str  # rubric, e.g. "kryterium_iii"
    side: str  # for | against | gap
    statement: str
    # Criterion III sphere of impact (economy, health, culture…) — the model proposes,
    # the human may change it; None = not classified
    sphere: str | None = None
    generated_at_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    generated_by_activity: str | None = None
    attributed_to_agent: str | None = None
    status: str = "candidate"  # candidate | accepted | rejected
    approved_by: str | None = None
    decided_at: datetime | None = None


class ArgumentClaim(SQLModel, table=True):
    """N:M link argument↔fact (prov:wasDerivedFrom)."""

    argument_id: int = Field(foreign_key="argument.id", primary_key=True)
    claim_id: int = Field(foreign_key="claim.id", primary_key=True)


class SpanNotVerified(ValueError):
    """Quote does not appear verbatim in the source — ground rejected (SAD §8.2)."""


def _enable_fk(engine: Engine) -> None:
    # SQLite enforces foreign keys only once enabled, per connection (§9.1).
    @event.listens_for(engine, "connect")
    def _set(dbapi_conn: object, _rec: object) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]


def _add_missing_columns(engine: Engine) -> None:
    """`create_all` makes new tables but never new columns on existing ones. Adds any
    missing NULLABLE column with a plain ALTER TABLE ADD COLUMN — the same statement on
    SQLite and Postgres, so no engine lock-in. ponytail: additive only; renames, type
    changes and NOT NULL columns wait for Alembic (TDD §3.3)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    ddl = col.type.compile(engine.dialect)
                    conn.execute(
                        text(
                            f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'
                        )
                    )


class ProvenanceStore:
    def __init__(self, db_url: str = "sqlite://") -> None:
        # StaticPool: one connection — fits the single-user profile and keeps the
        # in-memory DB alive across sessions of this instance (file-free tests).
        self.engine = create_engine(
            db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        _enable_fk(self.engine)
        SQLModel.metadata.create_all(self.engine)
        _add_missing_columns(self.engine)

    # --- sources ---

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
                raise ValueError(f"unknown source_id={source_id}")
            return src

    def list_sources(self) -> list[Source]:
        # ponytail: loads full_text too — fine for one operator's library; select
        #           columns if the sidebar gets slow
        with Session(self.engine) as s:
            return list(s.exec(select(Source).order_by(Source.id.desc())))  # type: ignore[union-attr]

    def source_by_local_identifier(self, local_identifier: str) -> Source | None:
        with Session(self.engine) as s:
            return s.exec(
                select(Source).where(Source.local_identifier == local_identifier)
            ).first()

    def set_signals(self, source_id: int, data: dict[str, object]) -> None:
        """Insert/refresh a source's signals. Merges by key: a metrics refresh keeps
        the pinned candidates."""
        with Session(self.engine) as s:
            row = s.get(SourceSignals, source_id)
            old = dict(row.data) if row is not None else {}
            s.merge(
                SourceSignals(
                    source_id=source_id,
                    data={**old, **data},
                    fetched_at=datetime.now(UTC),
                )
            )
            s.commit()

    def pin_candidate(self, source_id: int, candidate: dict[str, str]) -> None:
        """Pins a document the human picked as a likely impact trail (e.g. a policy
        paper citing this work). Corroboration checks pinned candidates FIRST. Still
        a candidate (Z1): it counts only once a verbatim quote from it is verified."""
        pinned = self.pinned_candidates(source_id)
        if all(p.get("url") != candidate["url"] for p in pinned):
            pinned.append(candidate)
        self.set_signals(source_id, {"pinned": pinned})

    def pinned_candidates(self, source_id: int) -> list[dict[str, str]]:
        raw = (self.get_signals(source_id) or {}).get("pinned")
        return cast(list[dict[str, str]], raw) if isinstance(raw, list) else []

    def get_signals(self, source_id: int) -> dict[str, object] | None:
        with Session(self.engine) as s:
            row = s.get(SourceSignals, source_id)
            return dict(row.data) if row is not None else None

    # --- grounds (verbatim anchors) ---

    def add_evidence(
        self,
        source_id: int,
        quote: str,
        *,
        activity: str | None = None,
        agent: str | None = None,
    ) -> int:
        """Store a ground only if the quote verifies against the source; else error."""
        with Session(self.engine) as s:
            src = s.get(Source, source_id)
            if src is None:
                raise ValueError(f"unknown source_id={source_id}")
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
                raise ValueError(f"unknown ev_id={ev_id}")
            return ev

    def evidence_for_source(self, source_id: int) -> list[Evidence]:
        with Session(self.engine) as s:
            return list(s.exec(select(Evidence).where(Evidence.source_id == source_id)))

    def evidence_for_claim(self, claim_id: int) -> list[Evidence]:
        stmt = (
            select(Evidence)
            .join(ClaimEvidence, ClaimEvidence.evidence_id == Evidence.id)  # type: ignore[arg-type]
            .where(ClaimEvidence.claim_id == claim_id)
        )
        with Session(self.engine) as s:
            return list(s.exec(stmt))

    def external_evidence_for_claim(self, claim_id: int) -> list[Evidence]:
        """A fact's grounds from a DIFFERENT source than the fact itself — i.e.
        external impact confirmations (from corroboration). These document the
        impact."""
        claim = self.get_claim(claim_id)
        return [
            ev
            for ev in self.evidence_for_claim(claim_id)
            if ev.source_id != claim.source_id
        ]

    # --- facts ---

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
        """Create a fact linked to its grounds. Requires >=1 ground (rule: a fact
        without verified coverage does not exist)."""
        if not evidence_ids:
            raise ValueError("a fact must have at least one verified ground")
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

    def link_evidence(self, claim_id: int, evidence_id: int) -> None:
        """Link an existing piece of evidence to a fact (e.g. an external impact
        confirmation from a fetched page — a ground outside the fact's source)."""
        with Session(self.engine) as s:
            s.add(ClaimEvidence(claim_id=claim_id, evidence_id=evidence_id))
            s.commit()

    def get_claim(self, claim_id: int) -> Claim:
        with Session(self.engine) as s:
            claim = s.get(Claim, claim_id)
            if claim is None:
                raise ValueError(f"unknown claim_id={claim_id}")
            return claim

    def claims_for_source(
        self, source_id: int, status: str | None = None
    ) -> list[Claim]:
        stmt = select(Claim).where(Claim.source_id == source_id)
        if status is not None:
            stmt = stmt.where(Claim.status == status)
        with Session(self.engine) as s:
            return list(s.exec(stmt))

    # --- impact trail (suggester hint) + lead ---

    def set_external_trail(self, claim_id: int, trail: str) -> None:
        """Set the hint: unknown | internal | candidate. Not a gate — a human may
        change it; corroboration searches only 'candidate' facts (with a lead)."""
        with Session(self.engine) as s:
            claim = s.get(Claim, claim_id)
            if claim is None:
                raise ValueError(f"unknown claim_id={claim_id}")
            claim.external_trail = trail
            s.add(claim)
            s.commit()

    def upsert_lead(self, claim_id: int, lead: str, query: str) -> int:
        """Insert/update a fact's lead (one per fact). Returns the lead's id."""
        with Session(self.engine) as s:
            existing = s.exec(select(Lead).where(Lead.claim_id == claim_id)).first()
            if existing is not None:
                existing.lead = lead
                existing.query = query
                s.add(existing)
                s.commit()
                assert existing.id is not None
                return existing.id
            row = Lead(claim_id=claim_id, lead=lead, query=query)
            s.add(row)
            s.commit()
            s.refresh(row)
            assert row.id is not None
            return row.id

    def clear_lead(self, claim_id: int) -> None:
        """Delete a fact's lead (when the suggester reclassified it as internal)."""
        with Session(self.engine) as s:
            existing = s.exec(select(Lead).where(Lead.claim_id == claim_id)).first()
            if existing is not None:
                s.delete(existing)
                s.commit()

    def get_lead(self, claim_id: int) -> Lead | None:
        with Session(self.engine) as s:
            return s.exec(select(Lead).where(Lead.claim_id == claim_id)).first()

    def leads_for_source(self, source_id: int) -> list[Lead]:
        stmt = (
            select(Lead)
            .join(Claim, Claim.id == Lead.claim_id)  # type: ignore[arg-type]
            .where(Claim.source_id == source_id)
        )
        with Session(self.engine) as s:
            return list(s.exec(stmt))

    # --- human gate (on the fact) ---

    def _decide(self, claim_id: int, status: str, by: str | None) -> None:
        with Session(self.engine) as s:
            claim = s.get(Claim, claim_id)
            if claim is None:
                raise ValueError(f"unknown claim_id={claim_id}")
            claim.status = status
            claim.approved_by = by
            claim.decided_at = datetime.now(UTC)
            s.add(claim)
            s.commit()

    def accept_claim(self, claim_id: int, by: str | None = None) -> None:
        """Gate: a human accepts the fact (prov:wasAttributedTo Person)."""
        self._decide(claim_id, "accepted", by)

    def reject_claim(self, claim_id: int, by: str | None = None) -> None:
        """Gate: a human rejects the fact (prov:wasInvalidatedBy)."""
        self._decide(claim_id, "rejected", by)

    # --- arguments (rubric-based assessment) ---

    def add_argument(
        self,
        source_id: int,
        criterion: str,
        side: str,
        statement: str,
        claim_ids: list[int],
        *,
        activity: str | None = None,
        agent: str | None = None,
        sphere: str | None = None,
    ) -> int:
        """Create an argument linked to the facts it rests on. The fact list may be
        empty only for 'luka' (gap) — the phase enforces that, not the store."""
        with Session(self.engine) as s:
            arg = Argument(
                source_id=source_id,
                criterion=criterion,
                side=side,
                statement=statement,
                sphere=sphere,
                generated_by_activity=activity,
                attributed_to_agent=agent,
            )
            s.add(arg)
            s.commit()
            s.refresh(arg)
            assert arg.id is not None
            for cid in claim_ids:
                s.add(ArgumentClaim(argument_id=arg.id, claim_id=cid))
            s.commit()
            return arg.id

    def get_argument(self, argument_id: int) -> Argument:
        with Session(self.engine) as s:
            arg = s.get(Argument, argument_id)
            if arg is None:
                raise ValueError(f"unknown argument_id={argument_id}")
            return arg

    def arguments_for_source(
        self, source_id: int, criterion: str | None = None, status: str | None = None
    ) -> list[Argument]:
        stmt = select(Argument).where(Argument.source_id == source_id)
        if criterion is not None:
            stmt = stmt.where(Argument.criterion == criterion)
        if status is not None:
            stmt = stmt.where(Argument.status == status)
        with Session(self.engine) as s:
            return list(s.exec(stmt))

    def claims_for_argument(self, argument_id: int) -> list[Claim]:
        stmt = (
            select(Claim)
            .join(ArgumentClaim, ArgumentClaim.claim_id == Claim.id)  # type: ignore[arg-type]
            .where(ArgumentClaim.argument_id == argument_id)
        )
        with Session(self.engine) as s:
            return list(s.exec(stmt))

    def _decide_argument(self, argument_id: int, status: str, by: str | None) -> None:
        with Session(self.engine) as s:
            arg = s.get(Argument, argument_id)
            if arg is None:
                raise ValueError(f"unknown argument_id={argument_id}")
            arg.status = status
            arg.approved_by = by
            arg.decided_at = datetime.now(UTC)
            s.add(arg)
            s.commit()

    def set_argument_sphere(self, argument_id: int, sphere: str | None) -> None:
        """The human's correction of the proposed sphere."""
        with Session(self.engine) as s:
            arg = s.get(Argument, argument_id)
            if arg is None:
                raise ValueError(f"unknown argument_id={argument_id}")
            arg.sphere = sphere
            s.add(arg)
            s.commit()

    def accept_argument(self, argument_id: int, by: str | None = None) -> None:
        self._decide_argument(argument_id, "accepted", by)

    def reject_argument(self, argument_id: int, by: str | None = None) -> None:
        self._decide_argument(argument_id, "rejected", by)

    # --- audit ---

    def verify_span(self, source_id: int, ev_id: int) -> bool:
        """Audit (I-audit): recompute a stored ground's span against the source."""
        with Session(self.engine) as s:
            src = s.get(Source, source_id)
            ev = s.get(Evidence, ev_id)
            if src is None or ev is None:
                return False
            return find_span(src.full_text, ev.quote) == (ev.start, ev.end)
