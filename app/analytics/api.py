import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import repository, service
from app.analytics.schemas import EngineRunSummaryOut, ForecastRunOut, ForecastSummaryOut
from app.core.db import get_session
from app.discovery import repository as discovery_repository
from app.identity.dependencies import get_current_user
from app.identity.models import User

router = APIRouter(tags=["analytics"])


@router.post("/projects/{project_id}/forecast", response_model=ForecastSummaryOut)
async def run_forecast(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> ForecastSummaryOut:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    try:
        summary = await service.run_all_engines(session, project=project)
    except service.AssumptionSetMissingError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"No active assumption set for engine '{exc}'"
        ) from exc

    return ForecastSummaryOut(
        canonical_project_id=summary.canonical_project_id,
        runs=[
            EngineRunSummaryOut(engine_type=r.engine_type, status=r.status, error_detail=r.error_detail)
            for r in summary.runs
        ],
    )


@router.get("/projects/{project_id}/forecast-runs", response_model=list[ForecastRunOut])
async def get_forecast_runs(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[ForecastRunOut]:
    project = await discovery_repository.get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    runs = await repository.list_forecast_runs_for_project(session, project_id)
    return [
        ForecastRunOut(
            id=r.id,
            engine_type=r.engine_type,
            engine_version=r.engine_version,
            status=r.status,
            output=r.output,
            error_detail=r.error_detail,
            created_at=r.created_at,
        )
        for r in runs
    ]
