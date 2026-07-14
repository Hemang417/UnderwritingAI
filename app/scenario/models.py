import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.analytics.models import ForecastRunStatus
from app.core.db import Base


class ScenarioType(enum.StrEnum):
    BEAR = "bear"
    BASE = "base"
    BULL = "bull"
    CUSTOM = "custom"


class ScenarioAssumptionSet(Base):
    """Versioned, admin-configurable dimension deltas per scenario type
    (PRD 12.4: "no hardcoded constants; every assumption is a versioned
    configuration value"). Exactly one row per scenario_type has
    is_active=True, mirroring AnalyticsAssumptionSet's versioning
    discipline -- a new scenario definition is a new version, never an
    in-place edit, so a past ScenarioResult stays explainable against the
    exact config that produced it. scenario_type=custom rows let an Admin
    define an arbitrary named scenario purely via a new row, no code change.
    """

    __tablename__ = "scenario_assumption_sets"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_type: Mapped[ScenarioType] = mapped_column(Enum(ScenarioType, name="scenario_type"))
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    adjustments: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScenarioResult(Base):
    """One deterministic application of a ScenarioAssumptionSet to a
    project's latest successful base ForecastRuns (Pricing/Sales
    Velocity/Financial/Risk). `base_forecast_run_ids` pins the exact
    ForecastRun rows transformed, alongside `scenario_assumption_set_id` --
    together this is what makes "re-running against the same base runs +
    same scenario version reproduces byte-identical output" checkable, the
    same discipline ForecastRun.input_manifest uses one level down.
    """

    __tablename__ = "scenario_results"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("canonical_projects.id")
    )
    scenario_assumption_set_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scenario_assumption_sets.id")
    )
    base_forecast_run_ids: Mapped[dict] = mapped_column(JSON)
    # Set only when an approved ProjectScenarioOverride was actually merged
    # into this run's adjustments (never a pending/rejected one) -- makes
    # "which numbers were IC-facing vs. an analyst's unreviewed proposal"
    # a checkable fact about the result itself, not something to infer.
    project_override_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_scenario_overrides.id"), nullable=True
    )
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ForecastRunStatus] = mapped_column(Enum(ForecastRunStatus, name="forecast_run_status"))
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scenario_assumption_set: Mapped["ScenarioAssumptionSet"] = relationship()


class ProjectScenarioOverride(Base):
    """An analyst-proposed, project-specific deviation from the firm-wide
    ScenarioAssumptionSet for one scenario_type -- e.g. a harsher Bear case
    for a first-time developer in an oversupplied micro-market. `adjustments`
    is layered on top of (not a replacement for) the governed global
    adjustments: only the keys present here are overridden, so the change is
    an explicit, auditable diff rather than a silent full-scenario edit.

    Deliberately diverges from ManualOverrideDetail's (M4) "takes effect
    immediately, review is a non-blocking sign-off" pattern: a
    project-scenario override is a *subjective* judgment call about
    deal-specific risk severity feeding straight into IC-facing forecasts,
    not an objective fact correction -- so review here is blocking.
    run_scenario only merges an override once approved=True. Review is
    still a one-time recorded decision on append-only history: rejecting
    doesn't mutate or revert anything, a corrected proposal is a new row.

    Versioned like ScenarioAssumptionSet (version/is_active), not chained
    like DataPoint -- there's exactly one proposer's judgment in play here,
    not competing sources needing priority arbitration.
    """

    __tablename__ = "project_scenario_overrides"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("canonical_projects.id")
    )
    scenario_type: Mapped[ScenarioType] = mapped_column(Enum(ScenarioType, name="scenario_type"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    adjustments: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    submitted_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
