import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Developer(Base):
    """Canonical developer record. Name aliasing/dedup is future work (M2+,
    once adapter-sourced developer names need reconciling against this)."""

    __tablename__ = "developers"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CanonicalProject(Base):
    """The resolved project identity per PRD: state + RERA registration
    number + developer + project name. Only identity/display fields live
    here -- enriched attributes (pricing, inventory, ...) arrive from M2
    onward as DataPoints in the Acquisition & Normalization context, never
    as columns on this table.
    """

    __tablename__ = "canonical_projects"
    __table_args__ = (
        UniqueConstraint("state", "rera_registration_number", "developer_id", "project_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    developer_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("developers.id"))
    state: Mapped[str] = mapped_column(String(100))
    rera_registration_number: Mapped[str] = mapped_column(String(100))
    project_name: Mapped[str] = mapped_column(String(255), index=True)
    locality: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50))
    # Set only for projects created via the live MAHARERA discovery path
    # (see resolve_via_live_maharera) -- MAHARERA's own internal project
    # id, distinct from rera_registration_number. Lets acquisition fetch
    # this project's detail directly (fetch_detail_by_project_id) instead
    # of re-searching by name, and is how acquisition knows to route this
    # project to the live adapter instead of the fixture one (see
    # app/acquisition/service.py's _resolve_external_ref).
    maharera_project_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    developer: Mapped["Developer"] = relationship()


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_text: Mapped[str] = mapped_column(String(255))
    normalized_text: Mapped[str] = mapped_column(String(255), index=True)
    city_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandidateMatch(Base):
    """Audit trail for one scored candidate produced during a discovery run.

    Per-scorer scores are their own columns rather than a generic JSON blob:
    this field set is small, fixed, and known in advance (unlike adapter-
    sourced DataPoints), so plain columns keep it directly queryable and
    keep the "why was this ranked here" explanation legible without parsing
    JSON. `None` on an optional scorer column means that scorer didn't apply
    to this search (e.g. no city_hint was given), not that it scored zero.
    """

    __tablename__ = "candidate_matches"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_query_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("search_queries.id"))
    canonical_project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("canonical_projects.id")
    )
    score_exact_name: Mapped[float] = mapped_column(Float)
    score_fuzzy_name: Mapped[float] = mapped_column(Float)
    score_city: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_historical_selection: Mapped[float] = mapped_column(Float)
    composite_score: Mapped[float] = mapped_column(Float)
    # Every scored project gets a row here (full audit trail), but only the
    # ones that actually cleared show_threshold were presented to the
    # analyst -- confirm() must only accept a selection from that subset,
    # not from the full internal scoring set.
    shown: Mapped[bool] = mapped_column(Boolean, default=False)
    chosen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConfirmedMapping(Base):
    """`normalized search string (+ city hint) -> canonical project` cache.

    Lets a future search for the same string skip discovery/ranking
    entirely via "use previous selection" (PRD Search History).
    """

    __tablename__ = "confirmed_mappings"
    __table_args__ = (UniqueConstraint("normalized_search_string", "city_hint"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    normalized_search_string: Mapped[str] = mapped_column(String(255), index=True)
    city_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canonical_project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("canonical_projects.id")
    )
    confidence_at_confirmation: Mapped[float] = mapped_column(Float)
    confirmed_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hit_count: Mapped[int] = mapped_column(Integer, default=1)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RankingConfig(Base):
    """Versioned, admin-configurable ranking weights and decision
    thresholds. Exactly one row has is_active=True at a time; changing
    ranking behavior means inserting a new version, never editing weights
    in place, so past CandidateMatch rows stay explainable against the
    config version that actually produced them.
    """

    __tablename__ = "ranking_configs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer)
    weights: Mapped[dict] = mapped_column(JSON)
    auto_proceed_threshold: Mapped[float] = mapped_column(Float)
    show_threshold: Mapped[float] = mapped_column(Float)
    separation_margin: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
