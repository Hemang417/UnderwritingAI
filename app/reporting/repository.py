import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.reporting.models import Report, ReportSection, ReportVersion


async def get_report_by_project_id(session: AsyncSession, canonical_project_id: uuid.UUID) -> Report | None:
    stmt = select(Report).where(Report.canonical_project_id == canonical_project_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_report_by_id(session: AsyncSession, report_id: uuid.UUID) -> Report | None:
    return await session.get(Report, report_id)


async def create_report(session: AsyncSession, report: Report) -> Report:
    session.add(report)
    await session.flush()
    return report


async def get_latest_report_version(session: AsyncSession, report_id: uuid.UUID) -> ReportVersion | None:
    stmt = (
        select(ReportVersion)
        .where(ReportVersion.report_id == report_id)
        .order_by(ReportVersion.version_number.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def create_report_version(session: AsyncSession, version: ReportVersion) -> ReportVersion:
    session.add(version)
    await session.flush()
    return version


async def create_report_section(session: AsyncSession, section: ReportSection) -> ReportSection:
    session.add(section)
    await session.flush()
    return section


async def list_report_versions_for_project(
    session: AsyncSession, canonical_project_id: uuid.UUID
) -> list[ReportVersion]:
    stmt = (
        select(ReportVersion)
        .join(Report, ReportVersion.report_id == Report.id)
        .where(Report.canonical_project_id == canonical_project_id)
        .options(selectinload(ReportVersion.sections))
        .order_by(ReportVersion.version_number.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_report_version_by_id(session: AsyncSession, version_id: uuid.UUID) -> ReportVersion | None:
    stmt = (
        select(ReportVersion)
        .where(ReportVersion.id == version_id)
        .options(selectinload(ReportVersion.sections))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_report_section_by_id(session: AsyncSession, section_id: uuid.UUID) -> ReportSection | None:
    return await session.get(ReportSection, section_id)
