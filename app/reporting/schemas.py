import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CompletenessIssueOut(BaseModel):
    field_name: str
    issue: str


class GenerateReportRequest(BaseModel):
    force_override: bool = False


class ReportSectionOut(BaseModel):
    id: uuid.UUID
    section_name: str
    template_version: str
    generated_text: str
    guardrail_status: str
    guardrail_report: dict
    attempt_count: int
    created_at: datetime
    edited_text: str | None
    edited_by: uuid.UUID | None
    edited_at: datetime | None
    edited_guardrail_status: str | None
    edited_guardrail_report: dict | None
    guardrail_acknowledged_by: uuid.UUID | None
    guardrail_acknowledgment_note: str | None
    effective_text: str
    effective_guardrail_status: str


class ReportVersionOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    version_number: int
    status: str
    llm_provider: str
    guardrail_status: str | None
    completeness_issues: list[CompletenessIssueOut]
    completeness_overridden: bool
    created_by: uuid.UUID
    created_at: datetime
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_comments: str | None
    published_by: uuid.UUID | None
    published_at: datetime | None
    supersedes_version_id: uuid.UUID | None
    has_pdf: bool
    sections: list[ReportSectionOut]


class ReportVersionDetailOut(ReportVersionOut):
    generated_json: dict | None


class EditSectionRequest(BaseModel):
    text: str = Field(min_length=1)


class AcknowledgeGuardrailRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class ReviewDecisionRequest(BaseModel):
    approved: bool
    comments: str | None = Field(default=None, max_length=2000)


class SectionDiffOut(BaseModel):
    section_name: str
    changed: bool
    from_text: str | None
    to_text: str | None


class ValueDiffOut(BaseModel):
    path: str
    from_value: object
    to_value: object


class VersionComparisonOut(BaseModel):
    from_version_number: int
    to_version_number: int
    section_diffs: list[SectionDiffOut]
    changed_values: list[ValueDiffOut]
    added_paths: list[str]
    removed_paths: list[str]
