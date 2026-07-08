import uuid

from app.core.celery_app import celery_app
from app.core.db import SyncSessionLocal
from app.core.models import JobRun, JobStatus


@celery_app.task(name="core.health_check_echo", bind=True)
def health_check_echo(self, job_run_id: str, payload: dict) -> dict:
    """Trivial end-to-end proof task for M0.

    Marks its own JobRun row started -> success/failure in Postgres, which is
    the durable status source of truth per ADR-011 -- callers poll the DB row,
    never the Celery result backend, for job status.
    """
    run_id = uuid.UUID(job_run_id)
    with SyncSessionLocal() as session:
        job_run = session.get(JobRun, run_id)
        if job_run is None:
            return {"error": "job_run not found"}

        job_run.status = JobStatus.STARTED
        session.commit()

        try:
            result = {"echo": payload}
            job_run.status = JobStatus.SUCCESS
            job_run.result = result
            session.commit()
            return result
        except Exception as exc:  # pragma: no cover - defensive, trivial task
            job_run.status = JobStatus.FAILURE
            job_run.error = str(exc)
            session.commit()
            raise
