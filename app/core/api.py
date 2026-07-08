import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.models import JobRun
from app.core.tasks import health_check_echo
from app.identity.dependencies import get_current_user
from app.identity.models import User

jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])


class HealthCheckRequest(BaseModel):
    payload: dict = {}


class JobRunOut(BaseModel):
    id: uuid.UUID
    task_name: str
    status: str
    result: dict | None
    error: str | None

    model_config = {"from_attributes": True}


@jobs_router.post("/health-check", response_model=JobRunOut, status_code=status.HTTP_202_ACCEPTED)
async def trigger_health_check(
    body: HealthCheckRequest,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> JobRun:
    """Enqueues the M0 trivial task and returns the DB-tracked JobRun row.

    Per ADR-011, callers poll GET /jobs/{id} (a Postgres read) for status --
    never the Celery result backend directly.
    """
    job_run = JobRun(task_name="core.health_check_echo")
    session.add(job_run)
    await session.commit()
    await session.refresh(job_run)

    health_check_echo.delay(str(job_run.id), body.payload)
    return job_run


@jobs_router.get("/{job_id}", response_model=JobRunOut)
async def get_job_status(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> JobRun:
    job_run = await session.get(JobRun, job_id)
    if job_run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job run not found")
    return job_run
