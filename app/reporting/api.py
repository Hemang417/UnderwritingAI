import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.discovery import repository as discovery_repository
from app.identity.dependencies import get_current_user, require_permission
from app.identity.models import User
from app.llm.base import LLMProvider
from app.llm.dependencies import get_llm_provider
from app.reporting import repository, service
from app.reporting.models import ReportSection, ReportVersion
from app.reporting.schemas import (
    CompletenessIssueOut,
    GenerateReportRequest,
    ReportSectionOut,
    ReportVersionDetailOut,
    ReportVersionOut,
)

router = APIRouter(tags=["reporting"])


def _section_out(section: ReportSection) -> ReportSectionOut:
    return ReportSectionOut(
        id=section.id,
        section_name=section.section_name,
        template_version=section.template_version,
        generated_text=section.generated_text,
        guardrail_status=section.guardrail_status,
        guardrail_report=section.guardrail_report,
        attempt_count=section.attempt_count,
        created_at=section.created_at,
    )


def _version_out(version: ReportVersion) -> ReportVersionOut:
    return ReportVersionOut(
        id=version.id,
        report_id=version.report_id,
        version_number=version.version_number,
        status=version.status,
        llm_provider=version.llm_provider,
        guardrail_status=version.guardrail_status,
        completeness_issues=[CompletenessIssueOut(**i) for i in version.completeness_issues],
        completeness_overridden=version.completeness_overridden,
        created_by=version.created_by,
        created_at=version.created_at,
        sections=[_section_out(s) for s in version.sections],
    )


@router.post("/projects/{project_id}/reports/generate", response_model=ReportVersionOut)
async def generate_report(
    project_id: uuid.UUID,
    body: GenerateReportRequest,
    session: AsyncSession = Depends(get_session),
    llm_provider: LLMProvider = Depends(get_llm_provider),
    user: User = Depends(require_permission("report.create")),
) -> ReportVersionOut:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    try:
        version = await service.generate_report(
            session,
            project=project,
            requested_by=user.id,
            llm_provider=llm_provider,
            force_override=body.force_override,
        )
    except service.CompletenessGateBlockedError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Required fields are missing or stale. Resubmit with force_override=true to "
                    "proceed anyway (this will be logged on the resulting report version)."
                ),
                "issues": [i.to_dict() for i in exc.issues],
            },
        ) from exc

    return _version_out(version)


@router.get("/projects/{project_id}/reports", response_model=list[ReportVersionOut])
async def list_report_versions(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[ReportVersionOut]:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    versions = await repository.list_report_versions_for_project(session, project_id)
    return [_version_out(v) for v in versions]


@router.get("/report-versions/{version_id}", response_model=ReportVersionDetailOut)
async def get_report_version(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> ReportVersionDetailOut:
    version = await repository.get_report_version_by_id(session, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report version not found")

    return ReportVersionDetailOut(**_version_out(version).model_dump(), generated_json=version.generated_json)
