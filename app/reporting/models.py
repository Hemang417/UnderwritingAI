import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ReportVersionStatus(enum.StrEnum):
    GENERATING = "generating"
    DRAFT = "draft"
    FAILED = "failed"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    # No distinct terminal "rejected" state (SAD S5.2's flow diagram sends a
    # rejection straight back to Draft with comments, looping into the same
    # edit cycle, not a separate persisted state) -- reviewed_by/at and
    # review_comments are the audit trail for "this went through a rejected
    # review round," even though status reads DRAFT again afterward.
    SUPERSEDED = "superseded"  # a still-open (never-published) version abandoned by regeneration


class GuardrailStatus(enum.StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class Report(Base):
    """Project-scoped aggregate root. One row per project; all actual
    content lives in the append-only ReportVersion chain (SAD S2)."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("canonical_projects.id"), unique=True
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("report_versions.id", use_alter=True, name="fk_reports_current_version_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReportVersion(Base):
    """The immutable-once-published audit unit (SAD S2). `generated_json`
    is the frozen input snapshot persisted *before* any LLM call (SAD S12
    "Report JSON discipline") -- every number the guardrail checks against,
    and every number a reviewer later re-derives by hand, traces back to
    this exact JSON, not to whatever DataPoints/ForecastRuns happen to
    exist now.

    `supersedes_version_id` is a *forward* pointer set once, at creation,
    on the *new* row -- never a backward mutation of an old row's status
    (ADR-010's DB trigger enforces zero-exception immutability once
    status=published; a backward "mark the old one superseded" write would
    violate that for a report that regenerates after publishing). Which
    version is "current" is `Report.current_version_id`, not a status flag
    on old rows -- a Published row's status never changes again.
    """

    __tablename__ = "report_versions"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("reports.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[ReportVersionStatus] = mapped_column(
        Enum(ReportVersionStatus, name="report_version_status"), default=ReportVersionStatus.GENERATING
    )
    generated_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_provider: Mapped[str] = mapped_column(String(50))
    guardrail_status: Mapped[GuardrailStatus | None] = mapped_column(
        Enum(GuardrailStatus, name="guardrail_status"), nullable=True
    )
    # ADR-015: gating never proceeds silently -- issues found (if any) are
    # always recorded, whether or not an analyst chose to override them.
    completeness_issues: Mapped[list] = mapped_column(JSON, default=list)
    completeness_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Review + publish lifecycle (M8). Only the latest review round's
    # comments are retained on the row -- full multi-round review history
    # is a documented-not-solved MVP simplification, not silently dropped.
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("report_versions.id"), nullable=True
    )
    pdf_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)

    sections: Mapped[list["ReportSection"]] = relationship(order_by="ReportSection.created_at")


class ReportSection(Base):
    """One section's generated text plus its guardrail outcome.
    `template_version` pins the exact prompt template that produced
    `generated_text`, mirroring how ForecastRun.engine_version pins the
    code that produced a forecast -- both make a past output reproducible
    against the artifact that generated it.

    `generated_text`/`guardrail_status`/`guardrail_report` are the
    generation-time record and are never overwritten (SAD S5.2 "Analyst
    edits (overlay preserves original text)"). An analyst edit lands in
    `edited_text` with its own, separately re-run guardrail result --
    the effective text shown to a reviewer/PDF is `edited_text or
    generated_text`, but the original LLM output stays inspectable
    forever, same append-only discipline as everywhere else in this system.
    """

    __tablename__ = "report_sections"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("report_versions.id")
    )
    section_name: Mapped[str] = mapped_column(String(100))
    template_version: Mapped[str] = mapped_column(String(20))
    generated_text: Mapped[str] = mapped_column(Text)
    guardrail_status: Mapped[GuardrailStatus] = mapped_column(Enum(GuardrailStatus, name="guardrail_status"))
    # Full matched/unmatched breakdown (SAD S12 point 6), kept for reviewer
    # inspection even on a section that ultimately passed after regeneration.
    guardrail_report: Mapped[dict] = mapped_column(JSON)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edited_guardrail_status: Mapped[GuardrailStatus | None] = mapped_column(
        Enum(GuardrailStatus, name="guardrail_status"), nullable=True
    )
    edited_guardrail_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # SAD S12's "explicit logged human-acknowledged exception path for
    # intentional approximate qualitative numbers" -- lets an analyst's
    # edit proceed to submission despite a guardrail failure, on record.
    guardrail_acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    guardrail_acknowledgment_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def effective_text(self) -> str:
        """What a reviewer/PDF/comparison actually sees -- the analyst's
        edit if one exists, otherwise the original LLM output."""
        return self.edited_text if self.edited_text is not None else self.generated_text

    @property
    def effective_guardrail_status(self) -> GuardrailStatus:
        return self.edited_guardrail_status if self.edited_text is not None else self.guardrail_status
