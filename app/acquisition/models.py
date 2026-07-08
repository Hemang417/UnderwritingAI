import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class SourceType(enum.StrEnum):
    RERA = "rera"
    DEVELOPER_SITE = "developer_site"
    MARKET_DATA = "market_data"
    INFRASTRUCTURE = "infrastructure"
    NEWS = "news"
    GOVERNMENT_DATA = "government_data"
    MANUAL_OVERRIDE = "manual_override"


class AcquisitionRunStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"  # circuit open -- never attempted this run


class DataPointStatus(enum.StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CORROBORATED = "corroborated"
    CONFLICTING = "conflicting"
    OVERRIDDEN = "overridden"
    REJECTED = "rejected"


class OCRJobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class DataPointValueType(enum.StrEnum):
    TEXT = "text"
    NUMERIC = "numeric"
    DATE = "date"
    JSON = "json"


# Shared instance: value_type is defined identically on DataPoint and
# FieldCatalog, and this keeps the enum name string ("data_point_value_type")
# declared exactly once.
value_type_column = Enum(DataPointValueType, name="data_point_value_type")


class DataSource(Base):
    """A configured, adapter-backed external source instance.

    `adapter_key` resolves to a class via app.adapters.registry -- adding a
    new source is a new adapter class + a config row here, never an
    orchestrator change (ADR-004).
    """

    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"))
    adapter_key: Mapped[str] = mapped_column(String(100))
    jurisdiction: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # How much this source type is trusted in general (e.g. a government
    # filing vs. a developer's own marketing site) -- stamped onto every
    # DataPoint fetched from it as source_confidence, rather than a magic
    # number hardcoded in the acquisition service.
    base_confidence: Mapped[float] = mapped_column(Float, default=90.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Per PRD/SAD: scraping government/developer sites carries legal/ToS
    # risk independent of engineering controls. A source should not be used
    # by the orchestrator until this is explicitly set, regardless of
    # is_active -- kept as a separate flag so "configured but not yet
    # legally cleared" is a representable, visible state.
    legal_review_signed_off: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AcquisitionRun(Base):
    __tablename__ = "acquisition_runs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("canonical_projects.id")
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("data_sources.id"))
    status: Mapped[AcquisitionRunStatus] = mapped_column(
        Enum(AcquisitionRunStatus, name="acquisition_run_status"), default=AcquisitionRunStatus.PENDING
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    data_source: Mapped["DataSource"] = relationship()


class Document(Base):
    """A raw fetched artifact (e.g. a scanned quarterly progress report
    PDF/image) stored in object storage. Any adapter can produce one via
    get_documents()/get_quarterly_reports() -- this row is just the pointer
    plus enough metadata to route it to the OCR pipeline.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("canonical_projects.id")
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("data_sources.id"))
    doc_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(500))
    checksum: Mapped[str] = mapped_column(String(64))  # sha256 hex digest
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    data_source: Mapped["DataSource"] = relationship()


class OCRJob(Base):
    """One OCR execution against one Document. `ocr_confidence` is the
    engine's own aggregate confidence in its text recognition -- kept
    separate from a DataPoint's `extraction_confidence` (how well the
    doc-type parser's pattern matched within that text), per ADR-007.
    """

    __tablename__ = "ocr_jobs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"))
    engine: Mapped[str] = mapped_column(String(50))
    engine_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[OCRJobStatus] = mapped_column(
        Enum(OCRJobStatus, name="ocr_job_status"), default=OCRJobStatus.PENDING
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document"] = relationship()


class DataPoint(Base):
    """The atomic fact. Generic (entity_type, entity_id, field_name) rather
    than per-field columns (ADR-003): every field, present and future,
    across arbitrarily heterogeneous adapters, gets the same provenance/
    versioning/conflict-resolution treatment without a schema migration.
    """

    __tablename__ = "data_points"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    field_name: Mapped[str] = mapped_column(String(100), index=True)

    value_type: Mapped[DataPointValueType] = mapped_column(value_type_column)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[DataPointStatus] = mapped_column(
        Enum(DataPointStatus, name="data_point_status"), default=DataPointStatus.ACTIVE
    )

    source_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("data_sources.id"))
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acquisition_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("acquisition_runs.id"), nullable=True
    )
    ocr_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ocr_jobs.id"), nullable=True
    )

    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source_confidence: Mapped[float] = mapped_column(Float)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_confidence: Mapped[float] = mapped_column(Float)

    previous_data_point_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_points.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped["DataSource"] = relationship()


class ConflictResolutionLog(Base):
    __tablename__ = "conflict_resolution_logs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    field_name: Mapped[str] = mapped_column(String(100))
    winning_data_point_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_points.id")
    )
    losing_data_point_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_points.id")
    )
    rule_applied: Mapped[str] = mapped_column(String(255))
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FieldCatalog(Base):
    """Versioned config: what a field is, and which source wins when two
    sources disagree on it. Per ADR-006, conflict resolution is deterministic
    and configurable -- never a hardcoded if/else per field.
    """

    __tablename__ = "field_catalog"

    field_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_type: Mapped[DataPointValueType] = mapped_column(value_type_column)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Ordered best-first, e.g. ["rera", "developer_site"] -- RERA outranks
    # the developer's own site when they disagree.
    source_priority: Mapped[list[str]] = mapped_column(JSON)
    staleness_threshold_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Whether a manual override of this field additionally needs a
    # Reviewer's recorded sign-off (PRD/SAD "optional reviewer sign-off for
    # critical fields") -- e.g. a RERA-registered fact vs. a soft market
    # figure. The override still takes effect immediately either way; this
    # only governs whether a sign-off is expected afterward.
    requires_override_review: Mapped[bool] = mapped_column(Boolean, default=False)


class ManualOverrideDetail(Base):
    """Companion row for any DataPoint whose source is the reserved
    manual_override DataSource (ADR-014). The override itself is an
    ordinary DataPoint flowing through the exact same versioning machinery
    as any other write -- this table only carries the human-correction-
    specific facts: who, why, and (for critical fields) whether a Reviewer
    has signed off on it.
    """

    __tablename__ = "manual_override_details"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    data_point_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_points.id"), unique=True
    )
    overridden_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    data_point: Mapped["DataPoint"] = relationship()
