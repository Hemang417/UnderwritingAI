from app.adapters.base import AdapterCapability, BaseSourceAdapter
from app.adapters.fixture_client import FixtureClient
from app.adapters.registry import register_adapter

# Keyed by RERA registration number. Standing in for a real MahaRERA
# lookup until live scraping is legally cleared -- see ARD/SAD.
MAHA_RERA_FIXTURES: dict[str, dict] = {
    "P51900001234": {"unit_count": 450, "possession_date": "2027-12-31"},  # Lodha Park
    "P52100005678": {"unit_count": 210, "possession_date": "2026-06-30"},  # Godrej Park Avenue
}


@register_adapter("maha_rera")
class MahaRERAAdapter(BaseSourceAdapter):
    source_type = "rera"
    capabilities = frozenset({AdapterCapability.GET_PROJECT})

    def __init__(self, client: FixtureClient | None = None):
        self.client = client or FixtureClient(fixtures=MAHA_RERA_FIXTURES)

    async def get_project(self, external_ref: str) -> dict:
        return await self.client.fetch(external_ref)
