import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import CandidateMatch, ConfirmedMapping, SearchQuery

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_discovery_transactional_tables(db_session: AsyncSession):
    # Searches now genuinely commit (matching how every other write path in
    # this codebase persists), so confirmed_mappings/search history from one
    # test would otherwise bleed into the next (e.g. a stale ConfirmedMapping
    # or accumulated historical-selection hit counts changing another test's
    # ranking outcome). Reset before each test; seeded reference data
    # (developers/canonical_projects/ranking_configs) is untouched.
    await db_session.execute(delete(CandidateMatch))
    await db_session.execute(delete(ConfirmedMapping))
    await db_session.execute(delete(SearchQuery))
    await db_session.commit()
    yield


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "Discovery Tester", "password": "correct-horse-1"},
    )
    resp = await client.post("/auth/login", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_exact_match_with_city_auto_resolves(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)

    resp = await client.post(
        "/search", json={"raw_text": "Lodha Park", "city_hint": "Mumbai"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["auto_confirmed"] is True
    assert body["project"]["project_name"] == "Lodha Park"
    assert body["project"]["developer"] == "Lodha Group"


async def test_repeat_search_reuses_confirmed_mapping(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)

    first = await client.post(
        "/search", json={"raw_text": "Lodha Park", "city_hint": "Mumbai"}, headers=headers
    )
    assert first.json()["status"] == "resolved"

    second = await client.post(
        "/search", json={"raw_text": "Lodha Park", "city_hint": "Mumbai"}, headers=headers
    )
    body = second.json()
    assert body["status"] == "previous_mapping"
    assert body["project"]["project_name"] == "Lodha Park"
    assert body["mapping_id"] is not None


async def test_force_refresh_bypasses_previous_mapping(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)

    await client.post("/search", json={"raw_text": "Lodha Park", "city_hint": "Mumbai"}, headers=headers)

    refreshed = await client.post(
        "/search",
        json={"raw_text": "Lodha Park", "city_hint": "Mumbai", "force_refresh": True},
        headers=headers,
    )
    body = refreshed.json()
    assert body["status"] != "previous_mapping"


async def test_ambiguous_search_needs_confirmation(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)

    resp = await client.post("/search", json={"raw_text": "Green Valley"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "needs_confirmation"
    names = {c["project_name"] for c in body["candidates"]}
    assert {"Green Valley Residency", "Green Valley Heights"} <= names
    # ranked by descending confidence
    assert body["candidates"][0]["confidence_score"] >= body["candidates"][1]["confidence_score"]


async def test_confirm_candidate_creates_mapping_and_is_reused(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)

    search_resp = await client.post("/search", json={"raw_text": "Green Valley"}, headers=headers)
    body = search_resp.json()
    search_query_id = body["search_query_id"]
    chosen = body["candidates"][0]

    confirm_resp = await client.post(
        f"/search/{search_query_id}/confirm",
        json={"canonical_project_id": chosen["id"]},
        headers=headers,
    )
    assert confirm_resp.status_code == 200
    confirm_body = confirm_resp.json()
    assert confirm_body["project"]["id"] == chosen["id"]

    mapping = (
        await db_session.execute(
            select(ConfirmedMapping).where(ConfirmedMapping.id == confirm_body["mapping_id"])
        )
    ).scalar_one()
    assert str(mapping.canonical_project_id) == chosen["id"]
    assert mapping.hit_count == 1

    repeat_resp = await client.post("/search", json={"raw_text": "Green Valley"}, headers=headers)
    repeat_body = repeat_resp.json()
    assert repeat_body["status"] == "previous_mapping"
    assert repeat_body["project"]["id"] == chosen["id"]


async def test_confirm_rejects_project_not_in_candidate_set(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)

    search_resp = await client.post("/search", json={"raw_text": "Green Valley"}, headers=headers)
    search_query_id = search_resp.json()["search_query_id"]

    other_project = await client.post(
        "/search", json={"raw_text": "Lodha Park", "city_hint": "Mumbai"}, headers=headers
    )
    other_project_id = other_project.json()["project"]["id"]

    resp = await client.post(
        f"/search/{search_query_id}/confirm",
        json={"canonical_project_id": other_project_id},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_reuse_mapping_bumps_hit_count(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)

    search_resp = await client.post(
        "/search", json={"raw_text": "Lodha Park", "city_hint": "Mumbai"}, headers=headers
    )
    # Auto-resolve already created a mapping; look it up directly.
    mapping = (
        await db_session.execute(
            select(ConfirmedMapping).where(
                ConfirmedMapping.canonical_project_id == search_resp.json()["project"]["id"]
            )
        )
    ).scalar_one()
    mapping_id = mapping.id
    assert mapping.hit_count == 1

    reuse_resp = await client.post(f"/search/mappings/{mapping_id}/reuse", headers=headers)
    assert reuse_resp.status_code == 200

    db_session.expire_all()
    refreshed = await db_session.get(ConfirmedMapping, mapping_id)
    assert refreshed.hit_count == 2


async def test_no_match_for_unrelated_search(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)

    resp = await client.post("/search", json={"raw_text": "Xyzabc Nonexistent Towers"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_match"


async def test_get_project_by_id(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)

    search_resp = await client.post(
        "/search", json={"raw_text": "Lodha Park", "city_hint": "Mumbai"}, headers=headers
    )
    project_id = search_resp.json()["project"]["id"]

    resp = await client.get(f"/projects/{project_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["project_name"] == "Lodha Park"


async def test_get_project_not_found(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)
    resp = await client.get("/projects/00000000-0000-0000-0000-000000000000", headers=headers)
    assert resp.status_code == 404
