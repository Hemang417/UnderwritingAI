from app.adapters import maha_rera_live
from app.adapters.base import (
    AdapterCapability,
    AdapterPermanentError,
    AdapterTransientError,
    BaseSourceAdapter,
)
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


@register_adapter("maha_rera_live")
class LiveMahaRERAAdapter(BaseSourceAdapter):
    """Real MahaRERA adapter, calling MAHARERA's own public API (see
    app/adapters/maha_rera_live.py). Registered under a *separate*
    adapter_key from the fixture-backed one above, so the existing M0-M8
    pipeline (all seeded DataSource rows still point at "maha_rera") is
    completely untouched -- this only activates where explicitly wired in
    (currently: app.discovery.service.resolve_via_live_maharera).

    Requires a session token obtained by a human solving a CAPTCHA via
    `python scripts/setup_maharera_session.py` -- see maha_rera_live's and
    maha_rera_session's module docstrings.
    Confirmed by inspecting every wrapped MAHARERA endpoint: unit count is
    not exposed by this API, so get_project() never returns it (the
    acquisition service only writes fields actually present in a payload,
    so omitting it is safe -- it simply leaves that field to another
    source, exactly like a real gap in source coverage should behave).
    """

    source_type = "rera"
    capabilities = frozenset({AdapterCapability.SEARCH_PROJECT, AdapterCapability.GET_PROJECT})

    def __init__(self, client: maha_rera_live.MahaRERALiveClient | None = None):
        self.client = client or maha_rera_live.MahaRERALiveClient()

    async def search_project(self, criteria: dict) -> list[dict]:
        """criteria: {"project_name": str}. MAHARERA's live search only
        filters server-side by project name -- there's no reliable way to
        search by RERA registration number alone (confirmed in practice: a
        bounded scan of the unfiltered project list essentially never
        reaches an arbitrary project), so registration-number search isn't
        offered here.
        """
        project_name = (criteria.get("project_name") or "").strip()
        return await self._search_pages(project_name)

    async def _search_pages(self, project_name: str, *, page: int = 1) -> list[dict]:
        try:
            return await self.client.search(project_name=project_name, page=page)
        except maha_rera_live.MahaRERAAuthError as exc:
            raise AdapterPermanentError(str(exc)) from exc
        except maha_rera_live.MahaRERALiveError as exc:
            raise AdapterTransientError(str(exc)) from exc

    async def get_project(self, external_ref: str) -> dict:
        """external_ref = MAHARERA's own internal project_id (NOT the RERA
        registration number -- that's the fixture adapter's convention,
        not this one's). Captured once at discovery time in
        CanonicalProject.maharera_project_id (see resolve_via_live_maharera)
        and supplied here by the acquisition service on every subsequent
        run, so this never needs to re-search by name.
        """
        return await self.fetch_detail_by_project_id(external_ref)

    async def fetch_detail_by_project_id(self, project_id: str) -> dict:
        """Fetches Tier 2 detail for an already-known MAHARERA project_id.
        Returns only the fields this platform's FieldCatalog tracks --
        currently just possession_date. Never returns unit_count."""
        try:
            general = await self.client.get_general_details(project_id)
        except maha_rera_live.MahaRERAAuthError as exc:
            raise AdapterPermanentError(str(exc)) from exc
        except maha_rera_live.MahaRERALiveError as exc:
            raise AdapterTransientError(str(exc)) from exc

        if not general:
            raise AdapterPermanentError(f"No general details returned for MAHARERA project_id={project_id}")

        fields = maha_rera_live.map_general_details(general)
        result: dict = {}
        possession_date = fields.get("proposed_completion_date")
        if possession_date:
            result["possession_date"] = possession_date
        return result

    async def fetch_identity_by_project_id(self, project_id: str) -> dict:
        """Richer fetch for *identity* purposes (creating a new
        CanonicalProject) -- project name, developer, location, status.
        Distinct from fetch_detail_by_project_id, which deliberately
        returns only the narrow FieldCatalog-tracked subset written as
        DataPoints; identity fields are used once, at discovery time, not
        stored as versioned facts the same way.
        """
        try:
            general = await self.client.get_general_details(project_id)
            promoter = await self.client.get_promoter_details(project_id)
            address = await self.client.get_land_address(project_id)
        except maha_rera_live.MahaRERAAuthError as exc:
            raise AdapterPermanentError(str(exc)) from exc
        except maha_rera_live.MahaRERALiveError as exc:
            raise AdapterTransientError(str(exc)) from exc

        if not general:
            raise AdapterPermanentError(f"No general details returned for MAHARERA project_id={project_id}")

        return {
            **maha_rera_live.map_general_details(general),
            **maha_rera_live.map_promoter_details(promoter or {}),
            **maha_rera_live.map_address(address or {}),
        }
