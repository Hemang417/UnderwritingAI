import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.models import AcquisitionRun, ConflictResolutionLog, DataPoint
from app.analytics.models import ForecastRun
from app.discovery.models import CanonicalProject

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_state(db_session: AsyncSession):
    await db_session.execute(delete(ForecastRun))
    await db_session.execute(delete(ConflictResolutionLog))
    await db_session.execute(delete(DataPoint))
    await db_session.execute(delete(AcquisitionRun))
    await db_session.commit()
    yield


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "Analytics Tester", "password": "correct-horse-1"},
    )
    resp = await client.post("/auth/login", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _project_id(db_session: AsyncSession, project_name: str) -> str:
    project = (
        await db_session.execute(
            select(CanonicalProject).where(CanonicalProject.project_name == project_name)
        )
    ).scalar_one()
    return str(project.id)


async def test_forecast_succeeds_for_all_engines_after_acquisition(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")

    await client.post(f"/projects/{project_id}/acquire", headers=headers)

    resp = await client.post(f"/projects/{project_id}/forecast", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    statuses = {r["engine_type"]: r["status"] for r in body["runs"]}
    assert statuses == {
        "pricing": "success",
        "sales_velocity": "success",
        "financial": "success",
        "risk": "success",
    }

    runs_resp = await client.get(f"/projects/{project_id}/forecast-runs", headers=headers)
    assert runs_resp.status_code == 200
    runs = runs_resp.json()
    assert len(runs) == 4

    pricing_run = next(r for r in runs if r["engine_type"] == "pricing")
    assert pricing_run["output"]["current_price_per_sqft"] == 18500.0
    assert len(pricing_run["output"]["horizons"]) == 5

    risk_run = next(r for r in runs if r["engine_type"] == "risk")
    assert 0 <= risk_run["output"]["composite_risk_score"] <= 100


async def test_forecast_is_insufficient_data_without_acquisition_except_risk(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")  # never acquired in this test

    resp = await client.post(f"/projects/{project_id}/forecast", headers=headers)
    assert resp.status_code == 200
    statuses = {r["engine_type"]: r["status"] for r in resp.json()["runs"]}
    assert statuses["pricing"] == "insufficient_data"
    assert statuses["sales_velocity"] == "insufficient_data"
    assert statuses["financial"] == "insufficient_data"
    assert statuses["risk"] == "success"  # risk always produces a result, per its documented design


async def test_rerunning_forecast_with_unchanged_inputs_is_deterministic(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await client.post(f"/projects/{project_id}/acquire", headers=headers)

    def latest_output_by_engine(runs: list[dict]) -> dict:
        # Ordered (engine_type, created_at desc) by the repository -- the
        # first row seen per engine_type is that engine's most recent run.
        latest: dict[str, dict] = {}
        for r in runs:
            latest.setdefault(r["engine_type"], r["output"])
        return latest

    await client.post(f"/projects/{project_id}/forecast", headers=headers)
    first_runs = (await client.get(f"/projects/{project_id}/forecast-runs", headers=headers)).json()
    first_outputs = latest_output_by_engine(first_runs)

    await client.post(f"/projects/{project_id}/forecast", headers=headers)
    second_runs = (await client.get(f"/projects/{project_id}/forecast-runs", headers=headers)).json()
    second_outputs = latest_output_by_engine(second_runs)

    assert len(second_runs) == 8  # 4 engines x 2 forecast runs -- nothing overwritten, both retained
    for engine_type in ("pricing", "sales_velocity", "financial", "risk"):
        # Same inputs, same config, same numbers -- the actual determinism
        # claim (PRD/SAD "re-running reproduces byte-identical output"),
        # checked end-to-end through the real API and a real Postgres round
        # trip, not just at the pure-function level.
        assert second_outputs[engine_type] == first_outputs[engine_type], f"{engine_type} changed on rerun"
