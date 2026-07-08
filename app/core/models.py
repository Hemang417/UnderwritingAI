import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"


class JobRun(Base):
    """Generic Celery task execution record.

    Per ADR-011, job/run status is always read from Postgres, never from the
    Celery result backend, so status survives a broker restart. This generic
    table exists to prove that wiring for M0; domain contexts (Acquisition,
    Analytics, Reporting) get their own purpose-built run tables from M2 onward
    rather than reusing this one.
    """

    __tablename__ = "job_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.PENDING
    )
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
