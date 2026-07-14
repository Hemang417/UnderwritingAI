import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition import repository as acquisition_repository
from app.acquisition.staleness import is_stale
from app.analytics import repository
from app.analytics.engines import financial, pricing, risk, sales_velocity
from app.analytics.engines.base import InputManifestEntry, InsufficientDataError
from app.analytics.models import EngineType, ForecastRun, ForecastRunStatus
from app.discovery.models import CanonicalProject


class AssumptionSetMissingError(Exception):
    """Setup error: no active AnalyticsAssumptionSet exists for an engine
    type -- should never happen outside a broken/unseeded environment."""


@dataclass
class EngineRunSummary:
    engine_type: EngineType
    status: ForecastRunStatus
    error_detail: str | None


@dataclass
class ForecastSummary:
    canonical_project_id: uuid.UUID
    runs: list[EngineRunSummary]


ENTITY_TYPE = "canonical_project"


async def _require_assumptions(session: AsyncSession, engine_type: EngineType) -> dict:
    assumption_set = await repository.get_active_assumption_set(session, engine_type)
    if assumption_set is None:
        raise AssumptionSetMissingError(engine_type)
    return assumption_set


async def _persist_run(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    engine_type: EngineType,
    engine_version: str | None,
    assumption_set_id: uuid.UUID,
    input_manifest: list[InputManifestEntry],
    output: dict | None,
    status: ForecastRunStatus,
    error_detail: str | None,
) -> ForecastRun:
    return await repository.create_forecast_run(
        session,
        ForecastRun(
            canonical_project_id=project_id,
            engine_type=engine_type,
            engine_version=engine_version or "unknown",
            assumption_set_id=assumption_set_id,
            input_manifest=[m.to_dict() for m in input_manifest],
            output=output,
            status=status,
            error_detail=error_detail,
        ),
    )


async def run_all_engines(session: AsyncSession, *, project: CanonicalProject) -> ForecastSummary:
    """Runs Pricing, Sales Velocity, Financial, and Risk in dependency
    order (Financial composes the first two's output; Risk is independent).
    Each engine's pure calculate() function never touches the DB -- this
    function does the fetching, sequencing, and persistence, keeping the
    math itself trivially unit-testable.
    """
    runs: list[EngineRunSummary] = []

    price_dp = await acquisition_repository.get_current_data_point(
        session, entity_type=ENTITY_TYPE, entity_id=project.id, field_name="current_price_per_sqft"
    )
    unit_count_dp = await acquisition_repository.get_current_data_point(
        session, entity_type=ENTITY_TYPE, entity_id=project.id, field_name="unit_count"
    )

    pricing_assumptions = await _require_assumptions(session, EngineType.PRICING)
    sv_assumptions = await _require_assumptions(session, EngineType.SALES_VELOCITY)
    financial_assumptions = await _require_assumptions(session, EngineType.FINANCIAL)
    risk_assumptions = await _require_assumptions(session, EngineType.RISK)

    # --- Pricing ---
    pricing_manifest = (
        [InputManifestEntry(price_dp.id, "current_price_per_sqft", price_dp.version)] if price_dp else []
    )
    pricing_output = None
    try:
        if price_dp is None:
            raise InsufficientDataError("no current_price_per_sqft data point exists for this project")
        pricing_output = pricing.calculate(
            current_price_per_sqft=price_dp.value_numeric, assumptions=pricing_assumptions.parameters
        )
        pricing_status, pricing_error = ForecastRunStatus.SUCCESS, None
    except InsufficientDataError as exc:
        pricing_status, pricing_error = ForecastRunStatus.INSUFFICIENT_DATA, str(exc)
    await _persist_run(
        session,
        project_id=project.id,
        engine_type=EngineType.PRICING,
        engine_version=pricing.ENGINE_VERSION,
        assumption_set_id=pricing_assumptions.id,
        input_manifest=pricing_manifest,
        output=pricing_output,
        status=pricing_status,
        error_detail=pricing_error,
    )
    runs.append(EngineRunSummary(EngineType.PRICING, pricing_status, pricing_error))

    # --- Sales Velocity ---
    sv_manifest = (
        [InputManifestEntry(unit_count_dp.id, "unit_count", unit_count_dp.version)] if unit_count_dp else []
    )
    sv_output = None
    try:
        if unit_count_dp is None:
            raise InsufficientDataError("no unit_count data point exists for this project")
        sv_output = sales_velocity.calculate(
            unit_count=unit_count_dp.value_numeric, assumptions=sv_assumptions.parameters
        )
        sv_status, sv_error = ForecastRunStatus.SUCCESS, None
    except InsufficientDataError as exc:
        sv_status, sv_error = ForecastRunStatus.INSUFFICIENT_DATA, str(exc)
    await _persist_run(
        session,
        project_id=project.id,
        engine_type=EngineType.SALES_VELOCITY,
        engine_version=sales_velocity.ENGINE_VERSION,
        assumption_set_id=sv_assumptions.id,
        input_manifest=sv_manifest,
        output=sv_output,
        status=sv_status,
        error_detail=sv_error,
    )
    runs.append(EngineRunSummary(EngineType.SALES_VELOCITY, sv_status, sv_error))

    # --- Financial (depends on Pricing + Sales Velocity outputs) ---
    financial_manifest = pricing_manifest + sv_manifest
    financial_output = None
    try:
        if pricing_output is None or sv_output is None:
            raise InsufficientDataError(
                "financial forecast requires successful pricing and sales velocity runs"
            )
        financial_output = financial.calculate(
            pricing_output=pricing_output,
            sales_velocity_output=sv_output,
            assumptions=financial_assumptions.parameters,
        )
        financial_status, financial_error = ForecastRunStatus.SUCCESS, None
    except InsufficientDataError as exc:
        financial_status, financial_error = ForecastRunStatus.INSUFFICIENT_DATA, str(exc)
    await _persist_run(
        session,
        project_id=project.id,
        engine_type=EngineType.FINANCIAL,
        engine_version=financial.ENGINE_VERSION,
        assumption_set_id=financial_assumptions.id,
        input_manifest=financial_manifest,
        output=financial_output,
        status=financial_status,
        error_detail=financial_error,
    )
    runs.append(EngineRunSummary(EngineType.FINANCIAL, financial_status, financial_error))

    # --- Risk (independent; always produces a result -- see engine docstring) ---
    pricing_signal = None
    if price_dp is not None:
        price_field_catalog_entry = await acquisition_repository.get_field_catalog_entry(
            session, "current_price_per_sqft"
        )
        pricing_signal = {
            "is_stale": is_stale(price_dp, price_field_catalog_entry) if price_field_catalog_entry else False,
            "composite_confidence": price_dp.composite_confidence,
        }
    risk_manifest = pricing_manifest
    risk_output = risk.calculate(
        project_status=project.status, pricing_signal=pricing_signal, assumptions=risk_assumptions.parameters
    )
    await _persist_run(
        session,
        project_id=project.id,
        engine_type=EngineType.RISK,
        engine_version=risk.ENGINE_VERSION,
        assumption_set_id=risk_assumptions.id,
        input_manifest=risk_manifest,
        output=risk_output,
        status=ForecastRunStatus.SUCCESS,
        error_detail=None,
    )
    runs.append(EngineRunSummary(EngineType.RISK, ForecastRunStatus.SUCCESS, None))

    await session.commit()
    return ForecastSummary(canonical_project_id=project.id, runs=runs)
