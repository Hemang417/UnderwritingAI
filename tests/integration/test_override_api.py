import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.models import (
    AcquisitionRun,
    ConflictResolutionLog,
    DataPoint,
    ManualOverrideDetail,
)
from app.discovery.models import CanonicalProject
from app.identity import repository as identity_repository
from app.identity.models import UserRole

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_acquisition_state(db_session: AsyncSession):
    await db_session.execute(delete(ManualOverrideDetail))
    await db_session.execute(delete(ConflictResolutionLog))
    await db_session.execute(delete(DataPoint))
    await db_session.execute(delete(AcquisitionRun))
    await db_session.commit()
    yield


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "Override Tester", "password": "correct-horse-1"},
    )
    resp = await client.post("/auth/login", json={"email": email, "password": "correct-horse-1"})
    return resp.json()["access_token"]


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    token = await _register_and_login(client, email)
    return {"Authorization": f"Bearer {token}"}


async def _promote_to_reviewer(db_session: AsyncSession, email: str, *, exclusive: bool = False) -> None:
    user = await identity_repository.get_user_by_email(db_session, email)
    reviewer_role = await identity_repository.get_role_by_name(db_session, "reviewer")
    if exclusive:
        # Registration always grants "analyst" by default; strip it so this
        # account is reviewer-only, for tests that need to prove an
        # endpoint truly requires a permission analysts don't have.
        await db_session.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db_session.add(UserRole(user_id=user.id, role_id=reviewer_role.id))
    await db_session.commit()
    # expire_on_commit=False means the already-loaded `user.user_roles`
    # collection (from the register/login calls earlier in this test)
    # wouldn't otherwise pick up this change on the next permission check.
    db_session.expire_all()


async def _lodha_park_id(db_session: AsyncSession) -> str:
    project = (
        await db_session.execute(
            select(CanonicalProject).where(CanonicalProject.project_name == "Lodha Park")
        )
    ).scalar_one()
    return str(project.id)


async def test_override_wins_over_higher_priority_existing_source(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)

    await client.post(f"/projects/{project_id}/acquire", headers=headers)
    before = (await client.get(f"/projects/{project_id}/data-points", headers=headers)).json()
    clean_current = next(d for d in before if d["field_name"] == "unit_count" and d["is_current"])
    assert clean_current["source_name"] == "MahaRERA"  # RERA won the M2 conflict, as expected

    resp = await client.post(
        f"/projects/{project_id}/data-points/unit_count/override",
        headers=headers,
        json={"value": 500, "reason": "Confirmed 500 units via site visit on 2026-07-01"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_review"] is True  # unit_count is a critical field
    assert body["data_point"]["value"] == 500
    assert body["data_point"]["source_name"] == "Manual Override"
    assert body["data_point"]["is_current"] is True
    assert body["data_point"]["status"] == "active"
    assert body["data_point"]["composite_confidence"] == 100.0

    after = (await client.get(f"/projects/{project_id}/data-points", headers=headers)).json()
    unit_count_points = [d for d in after if d["field_name"] == "unit_count"]
    current = [d for d in unit_count_points if d["is_current"]]
    assert len(current) == 1
    assert current[0]["source_name"] == "Manual Override"

    previously_current = next(d for d in unit_count_points if d["source_name"] == "MahaRERA")
    assert previously_current["is_current"] is False
    assert previously_current["status"] == "overridden"  # not "conflicting" or "superseded"


async def test_override_on_non_critical_field_does_not_require_review(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)
    await client.post(f"/projects/{project_id}/acquire", headers=headers)

    resp = await client.post(
        f"/projects/{project_id}/data-points/current_price_per_sqft/override",
        headers=headers,
        json={"value": 19000, "reason": "Updated per latest price list"},
    )
    assert resp.status_code == 200
    assert resp.json()["requires_review"] is False


async def test_override_unknown_field_returns_404(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)

    resp = await client.post(
        f"/projects/{project_id}/data-points/not_a_real_field/override",
        headers=headers,
        json={"value": 1, "reason": "test"},
    )
    assert resp.status_code == 404


async def test_override_requires_manual_override_permission(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    await _promote_to_reviewer(db_session, unique_email, exclusive=True)  # reviewer only, no analyst role
    project_id = await _lodha_park_id(db_session)

    resp = await client.post(
        f"/projects/{project_id}/data-points/unit_count/override",
        headers=headers,
        json={"value": 1, "reason": "test"},
    )
    assert resp.status_code == 403


async def test_review_flow_approve(client: AsyncClient, db_session: AsyncSession, unique_email: str):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)
    await client.post(f"/projects/{project_id}/acquire", headers=analyst_headers)

    override_resp = await client.post(
        f"/projects/{project_id}/data-points/unit_count/override",
        headers=analyst_headers,
        json={"value": 500, "reason": "Confirmed via site visit"},
    )
    override_id = override_resp.json()["override_id"]

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)

    review_resp = await client.post(
        f"/data-point-overrides/{override_id}/review",
        headers=reviewer_headers,
        json={"approved": True, "notes": "Verified with site engineer"},
    )
    assert review_resp.status_code == 200
    body = review_resp.json()
    assert body["approved"] is True
    assert body["notes"] == "Verified with site engineer"
    assert body["reviewed_at"] is not None

    # Review is a one-time sign-off, not an editable field.
    second_attempt = await client.post(
        f"/data-point-overrides/{override_id}/review",
        headers=reviewer_headers,
        json={"approved": False, "notes": "changed my mind"},
    )
    assert second_attempt.status_code == 400


async def test_review_requires_review_permission(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)
    await client.post(f"/projects/{project_id}/acquire", headers=analyst_headers)

    override_resp = await client.post(
        f"/projects/{project_id}/data-points/unit_count/override",
        headers=analyst_headers,
        json={"value": 500, "reason": "test"},
    )
    override_id = override_resp.json()["override_id"]

    # The analyst who created the override has no datapoint.review_override
    # permission -- self-review isn't possible.
    resp = await client.post(
        f"/data-point-overrides/{override_id}/review",
        headers=analyst_headers,
        json={"approved": True, "notes": None},
    )
    assert resp.status_code == 403


async def test_review_rejected_for_non_critical_field(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)
    await client.post(f"/projects/{project_id}/acquire", headers=analyst_headers)

    override_resp = await client.post(
        f"/projects/{project_id}/data-points/current_price_per_sqft/override",
        headers=analyst_headers,
        json={"value": 19000, "reason": "test"},
    )
    override_id = override_resp.json()["override_id"]

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)

    resp = await client.post(
        f"/data-point-overrides/{override_id}/review",
        headers=reviewer_headers,
        json={"approved": True, "notes": None},
    )
    assert resp.status_code == 400


async def test_review_unknown_override_returns_404(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    reviewer_headers = await _auth_headers(client, unique_email)
    await _promote_to_reviewer(db_session, unique_email)

    resp = await client.post(
        "/data-point-overrides/00000000-0000-0000-0000-000000000000/review",
        headers=reviewer_headers,
        json={"approved": True, "notes": None},
    )
    assert resp.status_code == 404
