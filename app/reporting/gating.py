import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition import repository as acquisition_repository
from app.acquisition.staleness import is_stale

ENTITY_TYPE = "canonical_project"

# Every field a report currently depends on (SAD S12 "Report JSON
# discipline" starts here -- a report can't be assembled around a field
# that hasn't been acquired yet).
REQUIRED_FIELDS = ["unit_count", "possession_date", "current_price_per_sqft"]


@dataclass(frozen=True)
class CompletenessIssue:
    field_name: str
    issue: str  # "missing" | "stale"

    def to_dict(self) -> dict:
        return {"field_name": self.field_name, "issue": self.issue}


async def check_completeness(
    session: AsyncSession, canonical_project_id: uuid.UUID
) -> list[CompletenessIssue]:
    """ADR-015: report generation blocks by default on missing/stale
    required fields, listing exactly which ones -- never proceeds silently.
    Returns an empty list when everything required is present and fresh.
    """
    issues: list[CompletenessIssue] = []
    for field_name in REQUIRED_FIELDS:
        data_point = await acquisition_repository.get_current_data_point(
            session, entity_type=ENTITY_TYPE, entity_id=canonical_project_id, field_name=field_name
        )
        if data_point is None:
            issues.append(CompletenessIssue(field_name, "missing"))
            continue

        field_catalog_entry = await acquisition_repository.get_field_catalog_entry(session, field_name)
        if field_catalog_entry is not None and is_stale(data_point, field_catalog_entry):
            issues.append(CompletenessIssue(field_name, "stale"))

    return issues
