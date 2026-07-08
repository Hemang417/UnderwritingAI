from app.adapters.base import AdapterCapability, BaseSourceAdapter
from app.adapters.fixture_client import FixtureClient
from app.adapters.registry import register_adapter

# Keyed by normalized project name (developer sites have no RERA-style
# registration number). Deliberately disagrees with the MahaRERA fixture on
# unit_count for Lodha Park (460 vs 450) so conflict resolution has a real
# case to resolve, not just clean agreement.
DEVELOPER_SITE_FIXTURES: dict[str, dict] = {
    "lodha park": {"unit_count": 460, "possession_date": "2027-12-31", "current_price_per_sqft": 18500},
    "godrej park avenue": {
        "unit_count": 205,
        "possession_date": "2026-06-30",
        "current_price_per_sqft": 9800,
    },
}


@register_adapter("developer_site")
class DeveloperSiteAdapter(BaseSourceAdapter):
    source_type = "developer_site"
    capabilities = frozenset({AdapterCapability.GET_PROJECT})

    def __init__(self, client: FixtureClient | None = None):
        self.client = client or FixtureClient(fixtures=DEVELOPER_SITE_FIXTURES)

    async def get_project(self, external_ref: str) -> dict:
        return await self.client.fetch(external_ref)
