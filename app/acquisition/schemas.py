import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceRunSummaryOut(BaseModel):
    data_source_name: str
    status: str
    error_detail: str | None
    fields_written: list[str]


class AcquisitionSummaryOut(BaseModel):
    canonical_project_id: uuid.UUID
    sources: list[SourceRunSummaryOut]


class DataPointOut(BaseModel):
    id: uuid.UUID
    field_name: str
    value: Any
    value_type: str
    source_name: str
    status: str
    is_current: bool
    is_stale: bool
    version: int
    source_confidence: float
    ocr_confidence: float | None
    extraction_confidence: float | None
    composite_confidence: float
    effective_date: date | None
    fetched_at: datetime


class DocumentIngestionOut(BaseModel):
    document_id: uuid.UUID
    ocr_job_id: uuid.UUID
    ocr_confidence: float
    fields_written: list[str]


class OverrideRequest(BaseModel):
    value: Any
    reason: str = Field(min_length=1, max_length=2000)


class OverrideOut(BaseModel):
    override_id: uuid.UUID
    data_point: DataPointOut
    requires_review: bool


class ReviewRequest(BaseModel):
    approved: bool
    notes: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    override_id: uuid.UUID
    approved: bool
    reviewed_by: uuid.UUID
    reviewed_at: datetime
    notes: str | None
