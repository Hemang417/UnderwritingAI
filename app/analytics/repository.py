import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.models import AnalyticsAssumptionSet, EngineType, ForecastRun


async def get_active_assumption_set(
    session: AsyncSession, engine_type: EngineType
) -> AnalyticsAssumptionSet | None:
    stmt = (
        select(AnalyticsAssumptionSet)
        .where(AnalyticsAssumptionSet.engine_type == engine_type, AnalyticsAssumptionSet.is_active.is_(True))
        .order_by(AnalyticsAssumptionSet.version.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def create_forecast_run(session: AsyncSession, forecast_run: ForecastRun) -> ForecastRun:
    session.add(forecast_run)
    await session.flush()
    return forecast_run


async def list_forecast_runs_for_project(
    session: AsyncSession, canonical_project_id: uuid.UUID
) -> list[ForecastRun]:
    stmt = (
        select(ForecastRun)
        .where(ForecastRun.canonical_project_id == canonical_project_id)
        .order_by(ForecastRun.engine_type, ForecastRun.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())
