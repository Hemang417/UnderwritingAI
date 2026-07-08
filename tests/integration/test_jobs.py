import pytest
from httpx import AsyncClient

from app.core.celery_app import celery_app

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _eager_celery():
    """Run tasks inline so job status is settled by the time .delay() returns,
    without needing a running worker process for this test."""
    original = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = original


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register", json={"email": email, "full_name": "Job Tester", "password": "correct-horse-1"}
    )
    resp = await client.post("/auth/login", json={"email": email, "password": "correct-horse-1"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_health_check_job_is_tracked_via_db_row(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)

    resp = await client.post("/jobs/health-check", json={"payload": {"ping": "pong"}}, headers=headers)
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    # Per ADR-011: status comes from the DB row, never the Celery result
    # backend directly -- this is exactly what this GET call proves out.
    status_resp = await client.get(f"/jobs/{job_id}", headers=headers)
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "success"
    assert body["result"] == {"echo": {"ping": "pong"}}


async def test_unknown_job_id_returns_404(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)
    resp = await client.get(
        "/jobs/00000000-0000-0000-0000-000000000000", headers=headers
    )
    assert resp.status_code == 404
