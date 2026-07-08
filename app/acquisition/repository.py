import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.acquisition.models import (
    AcquisitionRun,
    AcquisitionRunStatus,
    ConflictResolutionLog,
    DataPoint,
    DataSource,
    Document,
    FieldCatalog,
    ManualOverrideDetail,
    OCRJob,
    OCRJobStatus,
    SourceType,
)


async def get_data_source_by_id(session: AsyncSession, data_source_id: uuid.UUID) -> DataSource | None:
    return await session.get(DataSource, data_source_id)


async def get_data_source_by_adapter_key(session: AsyncSession, adapter_key: str) -> DataSource | None:
    stmt = select(DataSource).where(DataSource.adapter_key == adapter_key)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_active_data_sources(session: AsyncSession, *, jurisdiction: str | None) -> list[DataSource]:
    stmt = select(DataSource).where(
        DataSource.is_active.is_(True),
        DataSource.legal_review_signed_off.is_(True),
        # manual_override is a write-only channel for the override endpoint,
        # never something the orchestrator actively fetches from -- it must
        # never appear in a normal acquisition run's candidate source list.
        DataSource.source_type != SourceType.MANUAL_OVERRIDE,
    )
    sources = list((await session.execute(stmt)).scalars().all())
    # A source with no jurisdiction set applies everywhere (e.g. a
    # developer's own site); one with a jurisdiction only applies to
    # projects in that state.
    return [s for s in sources if s.jurisdiction is None or s.jurisdiction == jurisdiction]


async def get_field_catalog_entry(session: AsyncSession, field_name: str) -> FieldCatalog | None:
    return await session.get(FieldCatalog, field_name)


async def list_field_catalog(session: AsyncSession) -> list[FieldCatalog]:
    return list((await session.execute(select(FieldCatalog))).scalars().all())


async def create_acquisition_run(
    session: AsyncSession, *, canonical_project_id: uuid.UUID, data_source_id: uuid.UUID
) -> AcquisitionRun:
    run = AcquisitionRun(canonical_project_id=canonical_project_id, data_source_id=data_source_id)
    session.add(run)
    await session.flush()
    return run


async def complete_acquisition_run(
    session: AsyncSession,
    run: AcquisitionRun,
    *,
    status: AcquisitionRunStatus,
    attempt_count: int,
    error_detail: str | None,
) -> None:
    run.status = status
    run.attempt_count = attempt_count
    run.error_detail = error_detail
    run.completed_at = datetime.now(UTC)
    await session.flush()


async def get_current_data_point(
    session: AsyncSession, *, entity_type: str, entity_id: uuid.UUID, field_name: str
) -> DataPoint | None:
    stmt = (
        select(DataPoint)
        .where(
            DataPoint.entity_type == entity_type,
            DataPoint.entity_id == entity_id,
            DataPoint.field_name == field_name,
            DataPoint.is_current.is_(True),
        )
        .options(selectinload(DataPoint.source))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_data_point(session: AsyncSession, data_point: DataPoint) -> DataPoint:
    session.add(data_point)
    await session.flush()
    return data_point


async def create_conflict_log(session: AsyncSession, log: ConflictResolutionLog) -> None:
    session.add(log)
    await session.flush()


async def list_data_points_for_entity(
    session: AsyncSession, *, entity_type: str, entity_id: uuid.UUID
) -> list[DataPoint]:
    stmt = (
        select(DataPoint)
        .where(DataPoint.entity_type == entity_type, DataPoint.entity_id == entity_id)
        .options(selectinload(DataPoint.source))
        .order_by(DataPoint.field_name, DataPoint.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_document(
    session: AsyncSession,
    *,
    canonical_project_id: uuid.UUID,
    data_source_id: uuid.UUID,
    doc_type: str,
    storage_key: str,
    checksum: str,
) -> Document:
    document = Document(
        canonical_project_id=canonical_project_id,
        data_source_id=data_source_id,
        doc_type=doc_type,
        storage_key=storage_key,
        checksum=checksum,
    )
    session.add(document)
    await session.flush()
    return document


async def get_document_by_id(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return await session.get(Document, document_id)


async def create_ocr_job(
    session: AsyncSession, *, document_id: uuid.UUID, engine: str, engine_version: str
) -> OCRJob:
    job = OCRJob(document_id=document_id, engine=engine, engine_version=engine_version)
    session.add(job)
    await session.flush()
    return job


async def complete_ocr_job(
    session: AsyncSession,
    job: OCRJob,
    *,
    status: OCRJobStatus,
    raw_text: str | None,
    ocr_confidence: float | None,
    error_detail: str | None = None,
) -> None:
    job.status = status
    job.raw_text = raw_text
    job.ocr_confidence = ocr_confidence
    job.error_detail = error_detail
    job.completed_at = datetime.now(UTC)
    await session.flush()


async def create_manual_override_detail(
    session: AsyncSession, detail: ManualOverrideDetail
) -> ManualOverrideDetail:
    session.add(detail)
    await session.flush()
    return detail


async def get_manual_override_detail_by_id(
    session: AsyncSession, override_id: uuid.UUID
) -> ManualOverrideDetail | None:
    stmt = (
        select(ManualOverrideDetail)
        .where(ManualOverrideDetail.id == override_id)
        .options(selectinload(ManualOverrideDetail.data_point))
    )
    return (await session.execute(stmt)).scalar_one_or_none()
