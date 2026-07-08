import uuid
from datetime import UTC, date, datetime

from app.acquisition.models import DataPoint, DataPointValueType, FieldCatalog
from app.acquisition.staleness import is_stale


def _field_catalog(threshold_days: int | None) -> FieldCatalog:
    return FieldCatalog(
        field_name="unit_count",
        value_type=DataPointValueType.NUMERIC,
        source_priority=["rera"],
        staleness_threshold_days=threshold_days,
    )


def _data_point(*, effective_date=None, fetched_at=None) -> DataPoint:
    return DataPoint(
        id=uuid.uuid4(),
        entity_type="canonical_project",
        entity_id=uuid.uuid4(),
        field_name="unit_count",
        value_type=DataPointValueType.NUMERIC,
        value_numeric=450,
        source_id=uuid.uuid4(),
        source_confidence=95.0,
        composite_confidence=95.0,
        effective_date=effective_date,
        fetched_at=fetched_at or datetime.now(UTC),
    )


def test_never_stale_when_no_threshold_configured():
    dp = _data_point(effective_date=date(2000, 1, 1))
    assert is_stale(dp, _field_catalog(None), as_of=date(2026, 1, 1)) is False


def test_not_stale_within_threshold():
    dp = _data_point(effective_date=date(2026, 1, 1))
    assert is_stale(dp, _field_catalog(180), as_of=date(2026, 3, 1)) is False


def test_stale_past_threshold():
    dp = _data_point(effective_date=date(2025, 1, 1))
    assert is_stale(dp, _field_catalog(180), as_of=date(2026, 1, 1)) is True


def test_falls_back_to_fetched_at_when_no_effective_date():
    old_fetch = datetime(2025, 1, 1, tzinfo=UTC)
    dp = _data_point(effective_date=None, fetched_at=old_fetch)
    assert is_stale(dp, _field_catalog(180), as_of=date(2026, 1, 1)) is True
