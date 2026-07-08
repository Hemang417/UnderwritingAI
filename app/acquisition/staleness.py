from datetime import UTC, date, datetime

from app.acquisition.models import DataPoint, FieldCatalog


def is_stale(data_point: DataPoint, field_catalog_entry: FieldCatalog, *, as_of: date | None = None) -> bool:
    """PRD 10.2: every field type has a configured maximum age. Uses
    `effective_date` (the as-of date the fact pertains to) when known,
    falling back to `fetched_at` -- a field with no staleness threshold
    configured is never considered stale.
    """
    if field_catalog_entry.staleness_threshold_days is None:
        return False

    reference_date = data_point.effective_date or data_point.fetched_at.date()
    today = as_of or datetime.now(UTC).date()
    age_days = (today - reference_date).days
    return age_days > field_catalog_entry.staleness_threshold_days
