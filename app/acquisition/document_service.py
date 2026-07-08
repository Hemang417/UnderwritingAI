import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition import normalization, repository
from app.acquisition.document_parser import extract_fields
from app.acquisition.models import DataSource, OCRJobStatus
from app.core.storage import ObjectStorage
from app.discovery.models import CanonicalProject
from app.ocr.base import OCRProvider


class DataSourceNotFoundError(Exception):
    pass


@dataclass
class IngestionSummary:
    document_id: uuid.UUID
    ocr_job_id: uuid.UUID
    ocr_confidence: float
    fields_written: list[str] = field(default_factory=list)


async def ingest_document(
    session: AsyncSession,
    *,
    project: CanonicalProject,
    data_source: DataSource,
    doc_type: str,
    file_bytes: bytes,
    file_extension: str,
    storage: ObjectStorage,
    ocr_provider: OCRProvider,
) -> IngestionSummary:
    """Document -> OCRJob -> doc-type parser -> DataPoints, reusing the
    exact same conflict-resolution engine (normalization.write_field) that
    the clean structured-fetch path (M2) uses -- a scanned filing is just
    another way the same source's data reaches the platform, not a
    separate mechanism.
    """
    storage_key = f"{project.id}/{uuid.uuid4()}.{file_extension}"
    storage.save(storage_key, file_bytes)
    checksum = hashlib.sha256(file_bytes).hexdigest()

    document = await repository.create_document(
        session,
        canonical_project_id=project.id,
        data_source_id=data_source.id,
        doc_type=doc_type,
        storage_key=storage_key,
        checksum=checksum,
    )

    ocr_job = await repository.create_ocr_job(
        session,
        document_id=document.id,
        engine=ocr_provider.engine_name,
        engine_version=ocr_provider.engine_version,
    )

    try:
        # pytesseract shells out to the tesseract binary -- blocking, so it
        # runs off the event loop rather than stalling every other request.
        ocr_result = await asyncio.to_thread(ocr_provider.extract_text, file_bytes)
    except Exception as exc:
        await repository.complete_ocr_job(
            session,
            ocr_job,
            status=OCRJobStatus.FAILED,
            raw_text=None,
            ocr_confidence=None,
            error_detail=str(exc),
        )
        await session.commit()
        return IngestionSummary(document_id=document.id, ocr_job_id=ocr_job.id, ocr_confidence=0.0)

    await repository.complete_ocr_job(
        session,
        ocr_job,
        status=OCRJobStatus.SUCCESS,
        raw_text=ocr_result.text,
        ocr_confidence=ocr_result.confidence,
    )

    extracted_fields = extract_fields(doc_type, ocr_result.text)
    fields_written = []
    for extracted in extracted_fields:
        field_catalog_entry = await repository.get_field_catalog_entry(session, extracted.field_name)
        if field_catalog_entry is None:
            continue  # unrecognized field -- skip rather than guess a schema for it

        await normalization.write_field(
            session,
            entity_type="canonical_project",
            entity_id=project.id,
            field_name=extracted.field_name,
            raw_value=extracted.raw_value,
            source=data_source,
            source_ref=document.storage_key,
            ocr_job_id=ocr_job.id,
            source_confidence=data_source.base_confidence,
            ocr_confidence=ocr_result.confidence,
            extraction_confidence=extracted.extraction_confidence,
            field_catalog_entry=field_catalog_entry,
        )
        fields_written.append(extracted.field_name)

    await session.commit()
    return IngestionSummary(
        document_id=document.id,
        ocr_job_id=ocr_job.id,
        ocr_confidence=ocr_result.confidence,
        fields_written=fields_written,
    )
