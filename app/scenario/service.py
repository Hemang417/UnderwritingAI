import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import repository as analytics_repository
from app.analytics.engines import financial, pricing, sales_velocity
from app.analytics.engines.base import InsufficientDataError
from app.analytics.models import EngineType, ForecastRunStatus
from app.discovery.models import CanonicalProject
from app.scenario import repository
from app.scenario.adjusters import (
    FinancialParameterAdjuster,
    PricingParameterAdjuster,
    RiskCategoryAdjuster,
    SalesVelocityParameterAdjuster,
)
from app.scenario.models import ProjectScenarioOverride, ScenarioAssumptionSet, ScenarioResult, ScenarioType

_BASE_ENGINE_TYPES = (EngineType.PRICING, EngineType.SALES_VELOCITY, EngineType.FINANCIAL, EngineType.RISK)


class ScenarioAssumptionSetMissingError(Exception):
    """No active ScenarioAssumptionSet exists for a scenario_type -- should
    never happen outside a broken/unseeded environment."""


class BaseForecastMissingError(Exception):
    """The Scenario Engine transforms existing base ForecastRun outputs, it
    does not compute pricing/sales-velocity/financial/risk from scratch --
    raised when the project hasn't had a successful /forecast run yet."""


class ProjectOverrideNotFoundError(Exception):
    pass


class ProjectOverrideNotReviewableError(Exception):
    """Raised when reviewing an override that's already been reviewed, or
    has since been superseded by a newer proposal for the same
    project+scenario_type -- review is a one-time recorded sign-off on a
    still-live proposal, not an editable field."""


@dataclass
class ScenarioRunSummary:
    scenario_type: ScenarioType
    status: ForecastRunStatus
    error_detail: str | None


@dataclass
class ScenarioSummary:
    canonical_project_id: uuid.UUID
    runs: list[ScenarioRunSummary]


async def _latest_success_run(session: AsyncSession, project_id: uuid.UUID, engine_type: EngineType):
    runs = await analytics_repository.list_forecast_runs_for_project(session, project_id)
    for run in runs:
        if run.engine_type == engine_type and run.status == ForecastRunStatus.SUCCESS:
            return run
    return None


async def run_scenario(
    session: AsyncSession, *, project: CanonicalProject, scenario_assumption_set: ScenarioAssumptionSet
) -> ScenarioResult:
    """Applies one ScenarioAssumptionSet's dimension deltas to the
    project's latest successful base ForecastRuns and re-invokes the same
    pure M5 calculate() functions -- the Scenario Engine never duplicates
    engine math, only transforms the assumptions/scores fed into it.
    """
    project_override = await repository.get_active_project_override(
        session, project.id, scenario_assumption_set.scenario_type
    )
    applied_override = project_override if (project_override and project_override.approved) else None
    adjustments = {
        **scenario_assumption_set.adjustments,
        **(applied_override.adjustments if applied_override else {}),
    }

    base_run_ids: dict[str, str] = {}
    output: dict | None = None
    status, error_detail = ForecastRunStatus.SUCCESS, None

    try:
        base_runs = {}
        for engine_type in _BASE_ENGINE_TYPES:
            run = await _latest_success_run(session, project.id, engine_type)
            if run is None:
                raise BaseForecastMissingError(
                    f"project has no successful base '{engine_type}' forecast run yet -- "
                    "run POST /projects/{id}/forecast first"
                )
            base_runs[engine_type] = run
            base_run_ids[engine_type.value] = str(run.id)

        pricing_run = base_runs[EngineType.PRICING]
        sv_run = base_runs[EngineType.SALES_VELOCITY]
        financial_run = base_runs[EngineType.FINANCIAL]
        risk_run = base_runs[EngineType.RISK]

        pricing_assumptions = await analytics_repository.get_assumption_set_by_id(
            session, pricing_run.assumption_set_id
        )
        sv_assumptions = await analytics_repository.get_assumption_set_by_id(
            session, sv_run.assumption_set_id
        )
        financial_assumptions = await analytics_repository.get_assumption_set_by_id(
            session, financial_run.assumption_set_id
        )
        risk_assumptions = await analytics_repository.get_assumption_set_by_id(
            session, risk_run.assumption_set_id
        )

        pricing_params = PricingParameterAdjuster().adjust(pricing_assumptions.parameters, adjustments)
        scenario_pricing_output = pricing.calculate(
            current_price_per_sqft=pricing_run.output["current_price_per_sqft"], assumptions=pricing_params
        )

        sv_params = SalesVelocityParameterAdjuster().adjust(sv_assumptions.parameters, adjustments)
        scenario_sv_output = sales_velocity.calculate(
            unit_count=sv_run.output["unit_count"],
            units_sold_to_date=sv_run.output["units_sold_to_date"],
            assumptions=sv_params,
        )

        financial_params = FinancialParameterAdjuster().adjust(financial_assumptions.parameters, adjustments)
        scenario_financial_output = financial.calculate(
            pricing_output=scenario_pricing_output,
            sales_velocity_output=scenario_sv_output,
            assumptions=financial_params,
        )

        adjusted_category_scores = RiskCategoryAdjuster().adjust(
            risk_run.output["category_scores"], adjustments
        )
        weights = risk_assumptions.parameters["category_weights"]
        scenario_risk_output = {
            "category_scores": adjusted_category_scores,
            "category_explanations": risk_run.output["category_explanations"],
            "composite_risk_score": round(
                sum(adjusted_category_scores[category] * weight for category, weight in weights.items()), 2
            ),
        }

        output = {
            "pricing": scenario_pricing_output,
            "sales_velocity": scenario_sv_output,
            "financial": scenario_financial_output,
            "risk": scenario_risk_output,
        }
    except (BaseForecastMissingError, InsufficientDataError) as exc:
        status, error_detail = ForecastRunStatus.INSUFFICIENT_DATA, str(exc)

    return await repository.create_scenario_result(
        session,
        ScenarioResult(
            canonical_project_id=project.id,
            scenario_assumption_set_id=scenario_assumption_set.id,
            project_override_id=applied_override.id if applied_override else None,
            base_forecast_run_ids=base_run_ids,
            output=output,
            status=status,
            error_detail=error_detail,
        ),
    )


async def submit_project_override(
    session: AsyncSession,
    *,
    canonical_project_id: uuid.UUID,
    scenario_type: ScenarioType,
    adjustments: dict,
    reason: str,
    submitted_by: uuid.UUID,
) -> ProjectScenarioOverride:
    """Proposes a project-specific deviation. Retires any existing
    proposal (approved, rejected, or still pending) for this
    project+scenario_type -- at most one can ever be under consideration,
    full history preserved via version. Unlike M4's DataPoint overrides,
    this does NOT take effect immediately: it starts unapproved
    (approved=None) and run_scenario ignores it until a Reviewer approves.
    """
    previous = await repository.get_active_project_override(session, canonical_project_id, scenario_type)
    if previous is not None:
        previous.is_active = False

    override = ProjectScenarioOverride(
        canonical_project_id=canonical_project_id,
        scenario_type=scenario_type,
        version=(previous.version + 1) if previous else 1,
        is_active=True,
        adjustments=adjustments,
        reason=reason,
        submitted_by=submitted_by,
    )
    await repository.create_project_override(session, override)
    await session.commit()
    return override


async def review_project_override(
    session: AsyncSession,
    *,
    override_id: uuid.UUID,
    reviewed_by: uuid.UUID,
    approved: bool,
    notes: str | None,
) -> ProjectScenarioOverride:
    """Records a Reviewer's one-time sign-off. Rejecting does not revert or
    mutate anything else -- a corrected proposal is a new submission, same
    append-only discipline as review_override in M4."""
    override = await repository.get_project_override_by_id(session, override_id)
    if override is None:
        raise ProjectOverrideNotFoundError(override_id)
    if override.reviewed_by is not None:
        raise ProjectOverrideNotReviewableError("This override has already been reviewed")
    if not override.is_active:
        raise ProjectOverrideNotReviewableError(
            "This override has been superseded by a newer proposal for the same project and scenario"
        )

    override.reviewed_by = reviewed_by
    override.approved = approved
    override.review_notes = notes
    override.reviewed_at = datetime.now(UTC)
    await session.commit()
    return override


async def run_all_scenarios(session: AsyncSession, *, project: CanonicalProject) -> ScenarioSummary:
    runs: list[ScenarioRunSummary] = []
    for scenario_type in (ScenarioType.BEAR, ScenarioType.BASE, ScenarioType.BULL):
        assumption_set = await repository.get_active_scenario_assumption_set(session, scenario_type)
        if assumption_set is None:
            raise ScenarioAssumptionSetMissingError(scenario_type)
        result = await run_scenario(session, project=project, scenario_assumption_set=assumption_set)
        runs.append(ScenarioRunSummary(scenario_type, result.status, result.error_detail))

    await session.commit()
    return ScenarioSummary(canonical_project_id=project.id, runs=runs)
