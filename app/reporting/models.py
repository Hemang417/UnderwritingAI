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
    # in_review/published/rejected/superseded are M8 scope (Draft-only per
    # the M7 roadmap entry) -- additive later, not a breaking change.


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
    """The immutable audit unit (SAD S2). `generated_json` is the frozen
    input snapshot persisted *before* any LLM call (SAD S12 "Report JSON
    discipline") -- every number the guardrail checks against, and every
    number a reviewer later re-derives by hand, traces back to this exact
    JSON, not to whatever DataPoints/ForecastRuns happen to exist now.
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

    sections: Mapped[list["ReportSection"]] = relationship(order_by="ReportSection.created_at")


class ReportSection(Base):
    """One section's generated text plus its guardrail outcome.
    `template_version` pins the exact prompt template that produced
    `generated_text`, mirroring how ForecastRun.engine_version pins the
    code that produced a forecast -- both make a past output reproducible
    against the artifact that generated it.
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
