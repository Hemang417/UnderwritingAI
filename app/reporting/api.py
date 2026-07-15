import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.storage import LocalFilesystemStorage, ObjectStorage
from app.discovery import repository as discovery_repository
from app.identity import repository as identity_repository
from app.identity.dependencies import get_current_user, require_permission
from app.identity.models import User
from app.llm.base import LLMProvider
from app.llm.dependencies import get_llm_provider
from app.reporting import comparison, repository, service
from app.reporting.models import ReportSection, ReportVersion, ReportVersionStatus
from app.reporting.schemas import (
    AcknowledgeGuardrailRequest,
    CompletenessIssueOut,
    EditSectionRequest,
    GenerateReportRequest,
    ReportSectionOut,
    ReportVersionDetailOut,
    ReportVersionOut,
    ReviewDecisionRequest,
    SectionDiffOut,
    ValueDiffOut,
    VersionComparisonOut,
)

router = APIRouter(tags=["reporting"])


def get_storage() -> ObjectStorage:
    return LocalFilesystemStorage()


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
        edited_text=section.edited_text,
        edited_by=section.edited_by,
        edited_at=section.edited_at,
        edited_guardrail_status=section.edited_guardrail_status,
        edited_guardrail_report=section.edited_guardrail_report,
        guardrail_acknowledged_by=section.guardrail_acknowledged_by,
        guardrail_acknowledgment_note=section.guardrail_acknowledgment_note,
        effective_text=section.effective_text,
        effective_guardrail_status=section.effective_guardrail_status,
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
        reviewed_by=version.reviewed_by,
        reviewed_at=version.reviewed_at,
        review_comments=version.review_comments,
        published_by=version.published_by,
        published_at=version.published_at,
        supersedes_version_id=version.supersedes_version_id,
        has_pdf=version.pdf_storage_key is not None,
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


@router.patch("/report-versions/{version_id}/sections/{section_id}", response_model=ReportSectionOut)
async def edit_report_section(
    version_id: uuid.UUID,
    section_id: uuid.UUID,
    body: EditSectionRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_permission("report.edit_draft")),
) -> ReportSectionOut:
    try:
        section = await service.edit_section(
            session, section_id=section_id, new_text=body.text, edited_by=user.id
        )
    except service.SectionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found") from exc
    except service.SectionNotEditableError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if section.report_version_id != version_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found on this report version")
    return _section_out(section)


@router.post(
    "/report-versions/{version_id}/sections/{section_id}/acknowledge", response_model=ReportSectionOut
)
async def acknowledge_guardrail_failure(
    version_id: uuid.UUID,
    section_id: uuid.UUID,
    body: AcknowledgeGuardrailRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_permission("report.edit_draft")),
) -> ReportSectionOut:
    try:
        section = await service.acknowledge_section_guardrail_failure(
            session, section_id=section_id, acknowledged_by=user.id, note=body.note
        )
    except service.SectionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found") from exc
    except service.GuardrailAlreadyPassedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if section.report_version_id != version_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found on this report version")
    return _section_out(section)


@router.post("/report-versions/{version_id}/submit", response_model=ReportVersionOut)
async def submit_report_for_review(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("report.submit_review")),
) -> ReportVersionOut:
    try:
        version = await service.submit_for_review(session, version_id=version_id)
    except service.ReportVersionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report version not found") from exc
    except service.InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except service.UnacknowledgedGuardrailFailureError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "One or more sections have an unresolved guardrail failure. Edit them or "
                    "acknowledge the failure before submitting for review."
                ),
                "sections": exc.section_names,
            },
        ) from exc

    return _version_out(version)


@router.post("/report-versions/{version_id}/review", response_model=ReportVersionOut)
async def review_report_version(
    version_id: uuid.UUID,
    body: ReviewDecisionRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    storage: ObjectStorage = Depends(get_storage),
) -> ReportVersionOut:
    required_permission = "report.approve_publish" if body.approved else "report.reject"
    granted = await identity_repository.get_permission_names_for_user(session, user)
    if required_permission not in granted:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Missing required permission: {required_permission}"
        )

    version = await repository.get_report_version_by_id(session, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report version not found")
    report = await repository.get_report_by_id(session, version.report_id)
    project = await discovery_repository.get_project_by_id(session, report.canonical_project_id)

    try:
        version = await service.decide_review(
            session,
            version_id=version_id,
            reviewed_by=user.id,
            approved=body.approved,
            comments=body.comments,
            project=project,
            storage=storage,
        )
    except service.InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return _version_out(version)


@router.get("/report-versions/{version_id}/pdf")
async def download_report_pdf(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    version = await repository.get_report_version_by_id(session, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report version not found")
    if version.status != ReportVersionStatus.PUBLISHED or version.pdf_storage_key is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This report version has not been published yet")

    pdf_bytes = storage.load(version.pdf_storage_key)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-v{version.version_number}.pdf"'},
    )


@router.get("/report-versions/{from_version_id}/compare/{to_version_id}", response_model=VersionComparisonOut)
async def compare_report_versions(
    from_version_id: uuid.UUID,
    to_version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> VersionComparisonOut:
    from_version = await repository.get_report_version_by_id(session, from_version_id)
    to_version = await repository.get_report_version_by_id(session, to_version_id)
    if from_version is None or to_version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report version not found")
    if from_version.report_id != to_version.report_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Both versions must belong to the same report")

    result = comparison.compare_versions(from_version, to_version)
    return VersionComparisonOut(
        from_version_number=result.from_version_number,
        to_version_number=result.to_version_number,
        section_diffs=[SectionDiffOut(**vars(d)) for d in result.section_diffs],
        changed_values=[ValueDiffOut(**vars(d)) for d in result.changed_values],
        added_paths=result.added_paths,
        removed_paths=result.removed_paths,
    )
