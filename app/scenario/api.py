import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.discovery import repository as discovery_repository
from app.identity.dependencies import get_current_user, require_permission
from app.identity.models import User
from app.scenario import repository, service
from app.scenario.models import ScenarioType
from app.scenario.schemas import (
    ProjectOverrideOut,
    ProjectOverrideRequest,
    ScenarioOverrideReviewOut,
    ScenarioOverrideReviewRequest,
    ScenarioResultOut,
    ScenarioRunSummaryOut,
    ScenarioSummaryOut,
)

router = APIRouter(tags=["scenario"])


def _project_override_out(override) -> ProjectOverrideOut:
    return ProjectOverrideOut(
        id=override.id,
        canonical_project_id=override.canonical_project_id,
        scenario_type=override.scenario_type,
        version=override.version,
        adjustments=override.adjustments,
        reason=override.reason,
        submitted_by=override.submitted_by,
        approved=override.approved,
        reviewed_by=override.reviewed_by,
        reviewed_at=override.reviewed_at,
        review_notes=override.review_notes,
        created_at=override.created_at,
    )


@router.post("/projects/{project_id}/scenarios", response_model=ScenarioSummaryOut)
async def run_scenarios(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> ScenarioSummaryOut:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    try:
        summary = await service.run_all_scenarios(session, project=project)
    except service.ScenarioAssumptionSetMissingError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"No active scenario assumption set for '{exc}'"
        ) from exc

    return ScenarioSummaryOut(
        canonical_project_id=summary.canonical_project_id,
        runs=[
            ScenarioRunSummaryOut(scenario_type=r.scenario_type, status=r.status, error_detail=r.error_detail)
            for r in summary.runs
        ],
    )


@router.get("/projects/{project_id}/scenario-results", response_model=list[ScenarioResultOut])
async def get_scenario_results(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[ScenarioResultOut]:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    results = await repository.list_scenario_results_for_project(session, project_id)
    return [
        ScenarioResultOut(
            id=r.id,
            scenario_type=r.scenario_assumption_set.scenario_type,
            base_forecast_run_ids=r.base_forecast_run_ids,
            project_override_id=r.project_override_id,
            status=r.status,
            output=r.output,
            error_detail=r.error_detail,
            created_at=r.created_at,
        )
        for r in results
    ]


@router.post("/projects/{project_id}/scenarios/{scenario_type}/override", response_model=ProjectOverrideOut)
async def override_project_scenario(
    project_id: uuid.UUID,
    scenario_type: ScenarioType,
    body: ProjectOverrideRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_permission("scenario.override")),
) -> ProjectOverrideOut:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    override = await service.submit_project_override(
        session,
        canonical_project_id=project_id,
        scenario_type=scenario_type,
        adjustments=body.adjustments,
        reason=body.reason,
        submitted_by=user.id,
    )
    return _project_override_out(override)


@router.post("/project-scenario-overrides/{override_id}/review", response_model=ScenarioOverrideReviewOut)
async def review_project_scenario_override(
    override_id: uuid.UUID,
    body: ScenarioOverrideReviewRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_permission("scenario.review_override")),
) -> ScenarioOverrideReviewOut:
    try:
        override = await service.review_project_override(
            session,
            override_id=override_id,
            reviewed_by=user.id,
            approved=body.approved,
            notes=body.notes,
        )
    except service.ProjectOverrideNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Override not found") from exc
    except service.ProjectOverrideNotReviewableError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return ScenarioOverrideReviewOut(
        override_id=override.id,
        approved=override.approved,
        reviewed_by=override.reviewed_by,
        reviewed_at=override.reviewed_at,
        notes=override.review_notes,
    )


@router.get("/projects/{project_id}/scenario-overrides", response_model=list[ProjectOverrideOut])
async def get_project_scenario_overrides(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[ProjectOverrideOut]:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    overrides = await repository.list_project_overrides_for_project(session, project_id)
    return [_project_override_out(o) for o in overrides]
