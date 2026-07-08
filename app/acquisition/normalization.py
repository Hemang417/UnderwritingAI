import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition import repository
from app.acquisition.confidence import compute_composite_confidence
from app.acquisition.models import (
    ConflictResolutionLog,
    DataPoint,
    DataPointStatus,
    DataPointValueType,
    DataSource,
    FieldCatalog,
)


def _build_typed_values(value_type: DataPointValueType, raw_value) -> dict:
    if value_type == DataPointValueType.NUMERIC:
        return {"value_numeric": float(raw_value)}
    if value_type == DataPointValueType.DATE:
        parsed = raw_value if isinstance(raw_value, date) else datetime.strptime(raw_value, "%Y-%m-%d").date()
        return {"value_date": parsed}
    if value_type == DataPointValueType.JSON:
        return {"value_json": raw_value}
    return {"value_text": str(raw_value)}


def _values_equal(value_type: DataPointValueType, existing: DataPoint, new_typed: dict) -> bool:
    if value_type == DataPointValueType.NUMERIC:
        return existing.value_numeric == new_typed.get("value_numeric")
    if value_type == DataPointValueType.DATE:
        return existing.value_date == new_typed.get("value_date")
    if value_type == DataPointValueType.JSON:
        return existing.value_json == new_typed.get("value_json")
    return existing.value_text == new_typed.get("value_text")


def _priority_rank(source_type: str, priority: list[str]) -> int:
    try:
        return priority.index(source_type)
    except ValueError:
        return len(priority)  # unranked sources lose to any explicitly-ordered one


async def write_field(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
    raw_value,
    source: DataSource,
    source_ref: str | None,
    acquisition_run_id: uuid.UUID | None = None,
    ocr_job_id: uuid.UUID | None = None,
    source_confidence: float,
    ocr_confidence: float | None = None,
    extraction_confidence: float | None = None,
    effective_date: date | None = None,
    field_catalog_entry: FieldCatalog,
) -> DataPoint:
    """Write one field's value as a new DataPoint, applying deterministic
    conflict resolution (ADR-006). Three explicit paths: first-ever value,
    same-source refresh (plain version supersession), and cross-source
    disagreement (resolved by configured priority, logged, never averaged
    or silently dropped).

    Shared by both the clean structured-fetch path (M2, ocr/extraction
    confidence both None) and the OCR document-ingestion path (M3) -- one
    conflict-resolution engine regardless of how the value was obtained.
    """
    typed_values = _build_typed_values(field_catalog_entry.value_type, raw_value)
    existing_current = await repository.get_current_data_point(
        session, entity_type=entity_type, entity_id=entity_id, field_name=field_name
    )
    composite_confidence = compute_composite_confidence(
        source_confidence, ocr_confidence=ocr_confidence, extraction_confidence=extraction_confidence
    )

    new_dp = DataPoint(
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        value_type=field_catalog_entry.value_type,
        source_id=source.id,
        source_ref=source_ref,
        acquisition_run_id=acquisition_run_id,
        ocr_job_id=ocr_job_id,
        source_confidence=source_confidence,
        ocr_confidence=ocr_confidence,
        extraction_confidence=extraction_confidence,
        composite_confidence=composite_confidence,
        effective_date=effective_date,
        version=(existing_current.version + 1) if existing_current else 1,
        previous_data_point_id=existing_current.id if existing_current else None,
        **typed_values,
    )

    if existing_current is None:
        new_dp.is_current = True
        new_dp.status = DataPointStatus.ACTIVE
        await repository.create_data_point(session, new_dp)
        return new_dp

    if existing_current.source_id == source.id:
        existing_current.is_current = False
        existing_current.status = DataPointStatus.SUPERSEDED
        new_dp.is_current = True
        new_dp.status = DataPointStatus.ACTIVE
        await repository.create_data_point(session, new_dp)
        return new_dp

    priority = field_catalog_entry.source_priority
    existing_rank = _priority_rank(existing_current.source.source_type, priority)
    new_rank = _priority_rank(source.source_type, priority)
    new_wins = new_rank < existing_rank
    agree = _values_equal(field_catalog_entry.value_type, existing_current, typed_values)

    winner, loser = (new_dp, existing_current) if new_wins else (existing_current, new_dp)
    winner.is_current = True
    winner.status = DataPointStatus.ACTIVE
    loser.is_current = False
    loser.status = DataPointStatus.CORROBORATED if agree else DataPointStatus.CONFLICTING

    await repository.create_data_point(session, new_dp)

    if not agree:
        await repository.create_conflict_log(
            session,
            ConflictResolutionLog(
                entity_type=entity_type,
                entity_id=entity_id,
                field_name=field_name,
                winning_data_point_id=winner.id,
                losing_data_point_id=loser.id,
                rule_applied=f"source_priority:{priority}",
            ),
        )

    return new_dp


async def write_override(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
    raw_value,
    manual_override_source: DataSource,
    field_catalog_entry: FieldCatalog,
) -> DataPoint:
    """A manual correction always wins (PRD 11.1/ADR-014) -- this is a
    deliberate human decision, not a source disagreement to be arbitrated
    by field_catalog.source_priority (manual_override typically isn't even
    listed there). The previous value is marked `overridden`, distinct from
    `superseded`/`conflicting`, so the audit trail shows *why* it stopped
    being current.
    """
    typed_values = _build_typed_values(field_catalog_entry.value_type, raw_value)
    existing_current = await repository.get_current_data_point(
        session, entity_type=entity_type, entity_id=entity_id, field_name=field_name
    )
    composite_confidence = compute_composite_confidence(manual_override_source.base_confidence)

    new_dp = DataPoint(
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        value_type=field_catalog_entry.value_type,
        source_id=manual_override_source.id,
        source_confidence=manual_override_source.base_confidence,
        composite_confidence=composite_confidence,
        is_current=True,
        status=DataPointStatus.ACTIVE,
        version=(existing_current.version + 1) if existing_current else 1,
        previous_data_point_id=existing_current.id if existing_current else None,
        **typed_values,
    )

    if existing_current is not None:
        existing_current.is_current = False
        existing_current.status = DataPointStatus.OVERRIDDEN

    await repository.create_data_point(session, new_dp)
    return new_dp
