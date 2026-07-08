import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition import normalization, repository
from app.acquisition.models import DataPoint, ManualOverrideDetail


class FieldNotFoundError(Exception):
    pass


class ManualOverrideSourceMissingError(Exception):
    """Setup error: the reserved manual_override DataSource row doesn't
    exist -- should never happen outside a broken/unseeded environment."""


class OverrideNotFoundError(Exception):
    pass


class OverrideNotReviewableError(Exception):
    """Raised when reviewing an override that doesn't require review, or
    has already been reviewed once -- review is a one-time recorded
    sign-off, not an editable field."""


@dataclass
class OverrideResult:
    data_point: DataPoint
    override_detail: ManualOverrideDetail


async def submit_override(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
    raw_value,
    reason: str,
    overridden_by: uuid.UUID,
) -> OverrideResult:
    """A manual correction takes effect immediately (PRD 11.1) -- it does
    not wait on review. For fields marked requires_override_review in
    field_catalog, review is a recorded compliance sign-off that happens
    afterward (see review_override), not a gate on the correction itself.
    """
    field_catalog_entry = await repository.get_field_catalog_entry(session, field_name)
    if field_catalog_entry is None:
        raise FieldNotFoundError(field_name)

    manual_override_source = await repository.get_data_source_by_adapter_key(session, "manual_override")
    if manual_override_source is None:
        raise ManualOverrideSourceMissingError

    data_point = await normalization.write_override(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        raw_value=raw_value,
        manual_override_source=manual_override_source,
        field_catalog_entry=field_catalog_entry,
    )

    override_detail = ManualOverrideDetail(
        data_point_id=data_point.id,
        overridden_by=overridden_by,
        reason=reason,
        requires_review=field_catalog_entry.requires_override_review,
    )
    await repository.create_manual_override_detail(session, override_detail)

    await session.commit()
    return OverrideResult(data_point=data_point, override_detail=override_detail)


async def review_override(
    session: AsyncSession,
    *,
    override_id: uuid.UUID,
    reviewed_by: uuid.UUID,
    approved: bool,
    notes: str | None,
) -> ManualOverrideDetail:
    """Records a Reviewer's sign-off. Deliberately does not revert the
    DataPoint on rejection -- history is append-only throughout this
    system (ADR-003/ADR-010's spirit extended here); a rejected override
    is corrected by submitting a new override, not by mutating this one.
    """
    detail = await repository.get_manual_override_detail_by_id(session, override_id)
    if detail is None:
        raise OverrideNotFoundError(override_id)
    if not detail.requires_review:
        raise OverrideNotReviewableError("This field's overrides don't require reviewer sign-off")
    if detail.reviewed_by is not None:
        raise OverrideNotReviewableError("This override has already been reviewed")

    detail.reviewed_by = reviewed_by
    detail.approved = approved
    detail.review_notes = notes
    detail.reviewed_at = datetime.now(UTC)
    await session.commit()
    return detail
