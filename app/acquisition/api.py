import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition import document_service, override_service, repository, service
from app.acquisition.circuit_breaker import CircuitBreaker
from app.acquisition.models import DataPoint, DataPointValueType, FieldCatalog
from app.acquisition.orchestrator import AcquisitionOrchestrator
from app.acquisition.rate_limiter import RateLimiter
from app.acquisition.schemas import (
    AcquisitionSummaryOut,
    DataPointOut,
    DocumentIngestionOut,
    OverrideOut,
    OverrideRequest,
    ReviewOut,
    ReviewRequest,
    SourceRunSummaryOut,
)
from app.acquisition.staleness import is_stale
from app.core.db import get_session
from app.core.redis import redis_client
from app.core.storage import LocalFilesystemStorage, ObjectStorage
from app.discovery import repository as discovery_repository
from app.identity.dependencies import get_current_user, require_permission
from app.identity.models import User
from app.ocr.base import OCRProvider
from app.ocr.tesseract_provider import TesseractOCRProvider

router = APIRouter(tags=["acquisition"])


def get_orchestrator() -> AcquisitionOrchestrator:
    return AcquisitionOrchestrator(
        circuit_breaker=CircuitBreaker(redis_client),
        rate_limiter=RateLimiter(redis_client),
    )


def get_storage() -> ObjectStorage:
    return LocalFilesystemStorage()


def get_ocr_provider() -> OCRProvider:
    return TesseractOCRProvider()


def _extract_value(dp: DataPoint):
    if dp.value_type == DataPointValueType.NUMERIC:
        return dp.value_numeric
    if dp.value_type == DataPointValueType.DATE:
        return dp.value_date
    if dp.value_type == DataPointValueType.JSON:
        return dp.value_json
    return dp.value_text


def _data_point_out(dp: DataPoint, field_catalog_by_name: dict[str, FieldCatalog]) -> DataPointOut:
    field_catalog_entry = field_catalog_by_name.get(dp.field_name)
    stale = is_stale(dp, field_catalog_entry) if field_catalog_entry else False
    return DataPointOut(
        id=dp.id,
        field_name=dp.field_name,
        value=_extract_value(dp),
        value_type=dp.value_type,
        source_name=dp.source.name,
        status=dp.status,
        is_current=dp.is_current,
        is_stale=stale,
        version=dp.version,
        source_confidence=dp.source_confidence,
        ocr_confidence=dp.ocr_confidence,
        extraction_confidence=dp.extraction_confidence,
        composite_confidence=dp.composite_confidence,
        effective_date=dp.effective_date,
        fetched_at=dp.fetched_at,
    )


@router.post("/projects/{project_id}/acquire", response_model=AcquisitionSummaryOut)
async def acquire_project(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    orchestrator: AcquisitionOrchestrator = Depends(get_orchestrator),
    _user: User = Depends(get_current_user),
) -> AcquisitionSummaryOut:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    summary = await service.acquire_project_data(session, project=project, orchestrator=orchestrator)
    return AcquisitionSummaryOut(
        canonical_project_id=summary.canonical_project_id,
        sources=[
            SourceRunSummaryOut(
                data_source_name=s.data_source_name,
                status=s.status,
                error_detail=s.error_detail,
                fields_written=s.fields_written,
            )
            for s in summary.sources
        ],
    )


@router.post("/projects/{project_id}/documents", response_model=DocumentIngestionOut)
async def ingest_project_document(
    project_id: uuid.UUID,
    file: UploadFile,
    data_source_id: uuid.UUID = Form(...),
    doc_type: str = Form(...),
    session: AsyncSession = Depends(get_session),
    storage: ObjectStorage = Depends(get_storage),
    ocr_provider: OCRProvider = Depends(get_ocr_provider),
    _user: User = Depends(get_current_user),
) -> DocumentIngestionOut:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    data_source = await repository.get_data_source_by_id(session, data_source_id)
    if data_source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Data source not found")

    file_bytes = await file.read()
    file_extension = (file.filename or "bin").rsplit(".", 1)[-1]

    summary = await document_service.ingest_document(
        session,
        project=project,
        data_source=data_source,
        doc_type=doc_type,
        file_bytes=file_bytes,
        file_extension=file_extension,
        storage=storage,
        ocr_provider=ocr_provider,
    )
    return DocumentIngestionOut(
        document_id=summary.document_id,
        ocr_job_id=summary.ocr_job_id,
        ocr_confidence=summary.ocr_confidence,
        fields_written=summary.fields_written,
    )


@router.post("/projects/{project_id}/data-points/{field_name}/override", response_model=OverrideOut)
async def override_project_data_point(
    project_id: uuid.UUID,
    field_name: str,
    body: OverrideRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_permission("datapoint.manual_override")),
) -> OverrideOut:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    try:
        result = await override_service.submit_override(
            session,
            entity_type="canonical_project",
            entity_id=project_id,
            field_name=field_name,
            raw_value=body.value,
            reason=body.reason,
            overridden_by=user.id,
        )
    except override_service.FieldNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown field '{field_name}'") from exc

    # Re-fetch with the source relationship eager-loaded rather than
    # converting the just-written object directly, matching how every
    # other DataPoint -> DataPointOut conversion in this API works.
    field_catalog_by_name = {fc.field_name: fc for fc in await repository.list_field_catalog(session)}
    refreshed = await repository.get_current_data_point(
        session, entity_type="canonical_project", entity_id=project_id, field_name=field_name
    )
    return OverrideOut(
        override_id=result.override_detail.id,
        data_point=_data_point_out(refreshed, field_catalog_by_name),
        requires_review=result.override_detail.requires_review,
    )


@router.post("/data-point-overrides/{override_id}/review", response_model=ReviewOut)
async def review_data_point_override(
    override_id: uuid.UUID,
    body: ReviewRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_permission("datapoint.review_override")),
) -> ReviewOut:
    try:
        detail = await override_service.review_override(
            session,
            override_id=override_id,
            reviewed_by=user.id,
            approved=body.approved,
            notes=body.notes,
        )
    except override_service.OverrideNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Override not found") from exc
    except override_service.OverrideNotReviewableError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return ReviewOut(
        override_id=detail.id,
        approved=detail.approved,
        reviewed_by=detail.reviewed_by,
        reviewed_at=detail.reviewed_at,
        notes=detail.review_notes,
    )


@router.get("/projects/{project_id}/data-points", response_model=list[DataPointOut])
async def get_project_data_points(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[DataPointOut]:
    data_points = await repository.list_data_points_for_entity(
        session, entity_type="canonical_project", entity_id=project_id
    )
    field_catalog_by_name = {fc.field_name: fc for fc in await repository.list_field_catalog(session)}
    return [_data_point_out(dp, field_catalog_by_name) for dp in data_points]
