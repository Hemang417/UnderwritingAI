import uuid
from datetime import datetime

from pydantic import BaseModel


class EngineRunSummaryOut(BaseModel):
    engine_type: str
    status: str
    error_detail: str | None


class ForecastSummaryOut(BaseModel):
    canonical_project_id: uuid.UUID
    runs: list[EngineRunSummaryOut]


class ForecastRunOut(BaseModel):
    id: uuid.UUID
    engine_type: str
    engine_version: str
    status: str
    output: dict | None
    error_detail: str | None
    created_at: datetime
