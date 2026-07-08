import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition import normalization, repository
from app.acquisition.models import AcquisitionRunStatus, DataSource
from app.acquisition.orchestrator import AcquisitionOrchestrator
from app.adapters.registry import get_adapter
from app.discovery.models import CanonicalProject
from app.discovery.scoring import normalize_text


class ProjectNotFoundError(Exception):
    pass


@dataclass
class SourceRunSummary:
    data_source_name: str
    status: AcquisitionRunStatus
    error_detail: str | None
    fields_written: list[str] = field(default_factory=list)


@dataclass
class AcquisitionSummary:
    canonical_project_id: uuid.UUID
    sources: list[SourceRunSummary]


def _resolve_external_ref(data_source: DataSource, project: CanonicalProject) -> str | None:
    """Each source keys its records differently -- RERA by registration
    number, a developer's own site by project name. New adapters add a
    branch here, not a change to the orchestrator or normalization layer.
    """
    if data_source.adapter_key == "maha_rera":
        return project.rera_registration_number
    if data_source.adapter_key == "developer_site":
        return normalize_text(project.project_name)
    return None


async def acquire_project_data(
    session: AsyncSession,
    *,
    project: CanonicalProject,
    orchestrator: AcquisitionOrchestrator,
) -> AcquisitionSummary:
    data_sources = await repository.list_active_data_sources(session, jurisdiction=project.state)
    field_catalog_by_name = {fc.field_name: fc for fc in await repository.list_field_catalog(session)}

    summaries: list[SourceRunSummary] = []
    for data_source in data_sources:
        external_ref = _resolve_external_ref(data_source, project)
        if external_ref is None:
            summaries.append(
                SourceRunSummary(
                    data_source.name,
                    AcquisitionRunStatus.SKIPPED,
                    "no external_ref resolver registered for this adapter_key",
                )
            )
            continue

        run = await repository.create_acquisition_run(
            session, canonical_project_id=project.id, data_source_id=data_source.id
        )
        adapter = get_adapter(data_source.adapter_key)
        result = await orchestrator.execute_get_project(
            data_source_id=data_source.id, adapter=adapter, external_ref=external_ref
        )

        fields_written: list[str] = []
        if result.status == AcquisitionRunStatus.SUCCESS and result.raw_payload:
            for field_name, raw_value in result.raw_payload.items():
                field_catalog_entry = field_catalog_by_name.get(field_name)
                if field_catalog_entry is None:
                    continue  # unrecognized field -- skip rather than guess a schema for it
                await normalization.write_field(
                    session,
                    entity_type="canonical_project",
                    entity_id=project.id,
                    field_name=field_name,
                    raw_value=raw_value,
                    source=data_source,
                    source_ref=external_ref,
                    acquisition_run_id=run.id,
                    source_confidence=data_source.base_confidence,
                    field_catalog_entry=field_catalog_entry,
                )
                fields_written.append(field_name)

        await repository.complete_acquisition_run(
            session,
            run,
            status=result.status,
            attempt_count=result.attempt_count,
            error_detail=result.error_detail,
        )
        summaries.append(
            SourceRunSummary(data_source.name, result.status, result.error_detail, fields_written)
        )

    await session.commit()
    return AcquisitionSummary(canonical_project_id=project.id, sources=summaries)
