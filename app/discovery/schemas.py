import uuid
from typing import Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=255)
    city_hint: str | None = Field(default=None, max_length=100)
    force_refresh: bool = False


class ConfirmRequest(BaseModel):
    canonical_project_id: uuid.UUID


class ProjectOut(BaseModel):
    id: uuid.UUID
    project_name: str
    developer: str
    locality: str
    city: str
    state: str
    rera_registration_number: str
    status: str

    model_config = {"from_attributes": True}


class CandidateOut(ProjectOut):
    confidence_score: float


class SearchResponse(BaseModel):
    """One flexible envelope for the four possible outcomes of a search,
    per PRD: a prior confirmed mapping, an auto-resolved single match, an
    ambiguous set needing analyst confirmation, or no match at all."""

    status: Literal["previous_mapping", "resolved", "needs_confirmation", "no_match"]
    search_query_id: uuid.UUID | None = None
    mapping_id: uuid.UUID | None = None
    project: ProjectOut | None = None
    candidates: list[CandidateOut] | None = None
    auto_confirmed: bool | None = None


class ConfirmResponse(BaseModel):
    project: ProjectOut
    mapping_id: uuid.UUID


class LiveResolveRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=255)
