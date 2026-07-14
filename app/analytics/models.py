import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class EngineType(enum.StrEnum):
    PRICING = "pricing"
    SALES_VELOCITY = "sales_velocity"
    FINANCIAL = "financial"
    RISK = "risk"


class ForecastRunStatus(enum.StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"


class AnalyticsAssumptionSet(Base):
    """Versioned, admin-configurable parameters per engine (PRD "every
    assumption must be configurable" -- no hardcoded constants). Exactly one
    row per engine_type has is_active=True; changing assumptions means
    inserting a new version, never editing in place, so a past ForecastRun
    stays explainable against the exact config that produced it.
    """

    __tablename__ = "analytics_assumption_sets"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    engine_type: Mapped[EngineType] = mapped_column(Enum(EngineType, name="engine_type"))
    version: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForecastRun(Base):
    """One deterministic execution of one engine for one project. Per SAD:
    `input_manifest` pins the exact DataPoint versions read, and
    `engine_version` pins the code revision -- together with
    `assumption_set_id`, this is what makes "re-running against unchanged
    inputs+config reproduces byte-identical output" a checkable claim, not
    just an assertion.
    """

    __tablename__ = "forecast_runs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("canonical_projects.id")
    )
    engine_type: Mapped[EngineType] = mapped_column(Enum(EngineType, name="engine_type"))
    engine_version: Mapped[str] = mapped_column(String(20))
    assumption_set_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analytics_assumption_sets.id")
    )
    input_manifest: Mapped[list] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ForecastRunStatus] = mapped_column(Enum(ForecastRunStatus, name="forecast_run_status"))
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assumption_set: Mapped["AnalyticsAssumptionSet"] = relationship()
