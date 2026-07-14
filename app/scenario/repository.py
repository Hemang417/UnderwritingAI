import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.scenario.models import ProjectScenarioOverride, ScenarioAssumptionSet, ScenarioResult, ScenarioType


async def get_active_scenario_assumption_set(
    session: AsyncSession, scenario_type: ScenarioType
) -> ScenarioAssumptionSet | None:
    stmt = (
        select(ScenarioAssumptionSet)
        .where(
            ScenarioAssumptionSet.scenario_type == scenario_type,
            ScenarioAssumptionSet.is_active.is_(True),
        )
        .order_by(ScenarioAssumptionSet.version.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def create_scenario_result(session: AsyncSession, scenario_result: ScenarioResult) -> ScenarioResult:
    session.add(scenario_result)
    await session.flush()
    return scenario_result


async def list_scenario_results_for_project(
    session: AsyncSession, canonical_project_id: uuid.UUID
) -> list[ScenarioResult]:
    stmt = (
        select(ScenarioResult)
        .where(ScenarioResult.canonical_project_id == canonical_project_id)
        .options(selectinload(ScenarioResult.scenario_assumption_set))
        .order_by(ScenarioResult.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_active_project_override(
    session: AsyncSession, canonical_project_id: uuid.UUID, scenario_type: ScenarioType
) -> ProjectScenarioOverride | None:
    stmt = select(ProjectScenarioOverride).where(
        ProjectScenarioOverride.canonical_project_id == canonical_project_id,
        ProjectScenarioOverride.scenario_type == scenario_type,
        ProjectScenarioOverride.is_active.is_(True),
    )
    return (await session.execute(stmt)).scalars().first()


async def create_project_override(
    session: AsyncSession, override: ProjectScenarioOverride
) -> ProjectScenarioOverride:
    session.add(override)
    await session.flush()
    return override


async def get_project_override_by_id(
    session: AsyncSession, override_id: uuid.UUID
) -> ProjectScenarioOverride | None:
    return await session.get(ProjectScenarioOverride, override_id)


async def list_project_overrides_for_project(
    session: AsyncSession, canonical_project_id: uuid.UUID
) -> list[ProjectScenarioOverride]:
    stmt = (
        select(ProjectScenarioOverride)
        .where(ProjectScenarioOverride.canonical_project_id == canonical_project_id)
        .order_by(ProjectScenarioOverride.scenario_type, ProjectScenarioOverride.version.desc())
    )
    return list((await session.execute(stmt)).scalars().all())
