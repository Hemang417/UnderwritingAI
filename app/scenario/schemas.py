import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ScenarioRunSummaryOut(BaseModel):
    scenario_type: str
    status: str
    error_detail: str | None


class ScenarioSummaryOut(BaseModel):
    canonical_project_id: uuid.UUID
    runs: list[ScenarioRunSummaryOut]


class ScenarioResultOut(BaseModel):
    id: uuid.UUID
    scenario_type: str
    base_forecast_run_ids: dict
    project_override_id: uuid.UUID | None
    status: str
    output: dict | None
    error_detail: str | None
    created_at: datetime


class ProjectOverrideRequest(BaseModel):
    adjustments: dict
    reason: str = Field(min_length=1, max_length=2000)


class ProjectOverrideOut(BaseModel):
    id: uuid.UUID
    canonical_project_id: uuid.UUID
    scenario_type: str
    version: int
    adjustments: dict
    reason: str
    submitted_by: uuid.UUID
    approved: bool | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime


class ScenarioOverrideReviewRequest(BaseModel):
    approved: bool
    notes: str | None = Field(default=None, max_length=2000)


class ScenarioOverrideReviewOut(BaseModel):
    override_id: uuid.UUID
    approved: bool
    reviewed_by: uuid.UUID
    reviewed_at: datetime
    notes: str | None
