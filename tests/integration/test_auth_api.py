import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity import repository
from app.identity.models import UserRole

pytestmark = pytest.mark.asyncio


async def _register_and_login(client: AsyncClient, email: str, password: str = "correct-horse-1") -> str:
    resp = await client.post(
        "/auth/register", json={"email": email, "full_name": "Test User", "password": password}
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_register_defaults_to_analyst_role(client: AsyncClient, unique_email: str):
    resp = await client.post(
        "/auth/register",
        json={"email": unique_email, "full_name": "Ada Analyst", "password": "correct-horse-1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["roles"] == ["analyst"]


async def test_duplicate_registration_is_rejected(client: AsyncClient, unique_email: str):
    payload = {"email": unique_email, "full_name": "Dup", "password": "correct-horse-1"}
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409


async def test_login_with_wrong_password_is_rejected(client: AsyncClient, unique_email: str):
    await client.post(
        "/auth/register",
        json={"email": unique_email, "full_name": "Test", "password": "correct-horse-1"},
    )
    resp = await client.post("/auth/login", json={"email": unique_email, "password": "wrong"})
    assert resp.status_code == 401


async def test_me_requires_bearer_token(client: AsyncClient):
    resp = await client.get("/me")
    assert resp.status_code == 401


async def test_me_returns_authenticated_user(client: AsyncClient, unique_email: str):
    token = await _register_and_login(client, unique_email)
    resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == unique_email


async def test_analyst_is_denied_admin_endpoint(client: AsyncClient, unique_email: str):
    token = await _register_and_login(client, unique_email)
    resp = await client.get("/admin/ping", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_admin_role_is_granted_admin_endpoint(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    token = await _register_and_login(client, unique_email)

    # Promote the freshly-registered user to admin directly via the repository,
    # proving the RBAC gate reacts to role assignment, not registration order.
    user = await repository.get_user_by_email(db_session, unique_email)
    admin_role = await repository.get_role_by_name(db_session, "admin")
    db_session.add(UserRole(user_id=user.id, role_id=admin_role.id))
    await db_session.commit()
    # expire_on_commit=False (a deliberate perf choice for request-scoped
    # sessions) means the already-loaded `user.user_roles` collection isn't
    # refreshed by the commit above. In the real app this never matters --
    # every request gets a brand new session/identity map -- but this test
    # reuses one session across several steps, so it has to force a refresh
    # itself before relying on get_current_user's next lookup.
    db_session.expire_all()

    resp = await client.get("/admin/ping", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["acknowledged_by"] == unique_email
