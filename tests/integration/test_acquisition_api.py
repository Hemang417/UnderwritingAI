import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.models import AcquisitionRun, ConflictResolutionLog, DataPoint
from app.discovery.models import CanonicalProject

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_acquisition_state(db_session: AsyncSession):
    # Acquisition runs genuinely commit (same reasoning as discovery's
    # per-test reset), and circuit-breaker/rate-limiter state lives in Redis
    # keyed by data_source_id, which is stable across tests in this session
    # -- both need resetting so one test's simulated failures can't affect
    # another's.
    await db_session.execute(delete(ConflictResolutionLog))
    await db_session.execute(delete(DataPoint))
    await db_session.execute(delete(AcquisitionRun))
    await db_session.commit()

    redis = Redis.from_url("redis://localhost:6379/1", decode_responses=True)
    await redis.flushdb()
    await redis.aclose()
    yield


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "Acquisition Tester", "password": "correct-horse-1"},
    )
    resp = await client.post("/auth/login", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _lodha_park_id(db_session: AsyncSession) -> str:
    project = (
        await db_session.execute(
            select(CanonicalProject).where(CanonicalProject.project_name == "Lodha Park")
        )
    ).scalar_one()
    return str(project.id)


async def test_acquire_resolves_conflict_and_logs_it(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)

    resp = await client.post(f"/projects/{project_id}/acquire", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert {s["data_source_name"] for s in body["sources"]} == {"MahaRERA", "Developer Website"}
    assert all(s["status"] == "success" for s in body["sources"])

    dp_resp = await client.get(f"/projects/{project_id}/data-points", headers=headers)
    assert dp_resp.status_code == 200
    data_points = dp_resp.json()

    unit_count_points = [d for d in data_points if d["field_name"] == "unit_count"]
    assert len(unit_count_points) == 2
    active = next(d for d in unit_count_points if d["is_current"])
    conflicting = next(d for d in unit_count_points if not d["is_current"])
    assert active["source_name"] == "MahaRERA"  # RERA outranks developer_site per field_catalog
    assert active["value"] == 450
    assert active["status"] == "active"
    assert conflicting["source_name"] == "Developer Website"
    assert conflicting["value"] == 460
    assert conflicting["status"] == "conflicting"

    possession_points = [d for d in data_points if d["field_name"] == "possession_date"]
    assert len(possession_points) == 2
    assert {d["status"] for d in possession_points} == {"active", "corroborated"}
    assert all(d["value"] == "2027-12-31" for d in possession_points)  # both sources agree

    price_points = [d for d in data_points if d["field_name"] == "current_price_per_sqft"]
    assert len(price_points) == 1  # only the developer site supplies this field
    assert price_points[0]["source_name"] == "Developer Website"
    assert price_points[0]["value"] == 18500

    logs = (await db_session.execute(select(ConflictResolutionLog))).scalars().all()
    assert len(logs) == 1  # only the genuine disagreement (unit_count) gets logged
    assert logs[0].field_name == "unit_count"


async def test_data_points_empty_before_any_acquisition(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)

    resp = await client.get(f"/projects/{project_id}/data-points", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_acquire_unknown_project_returns_404(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)
    resp = await client.post(
        "/projects/00000000-0000-0000-0000-000000000000/acquire", headers=headers
    )
    assert resp.status_code == 404
