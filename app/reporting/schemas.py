import uuid
from datetime import datetime

from pydantic import BaseModel


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
    sections: list[ReportSectionOut]


class ReportVersionDetailOut(ReportVersionOut):
    generated_json: dict | None
