import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.models import AcquisitionRun, ConflictResolutionLog, DataPoint
from app.analytics.models import ForecastRun
from app.discovery.models import CanonicalProject
from app.identity import repository as identity_repository
from app.identity.models import UserRole
from app.scenario.models import ProjectScenarioOverride, ScenarioResult

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_state(db_session: AsyncSession):
    # ScenarioResult.project_override_id FKs into ProjectScenarioOverride --
    # must be deleted first or the FK constraint blocks the parent delete.
    await db_session.execute(delete(ScenarioResult))
    await db_session.execute(delete(ProjectScenarioOverride))
    await db_session.execute(delete(ForecastRun))
    await db_session.execute(delete(ConflictResolutionLog))
    await db_session.execute(delete(DataPoint))
    await db_session.execute(delete(AcquisitionRun))
    await db_session.commit()
    yield


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "Override Tester", "password": "correct-horse-1"},
    )
    resp = await client.post("/auth/login", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _promote_to_reviewer(db_session: AsyncSession, email: str, *, exclusive: bool = False) -> None:
    user = await identity_repository.get_user_by_email(db_session, email)
    reviewer_role = await identity_repository.get_role_by_name(db_session, "reviewer")
    if exclusive:
        await db_session.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db_session.add(UserRole(user_id=user.id, role_id=reviewer_role.id))
    await db_session.commit()
    db_session.expire_all()


async def _project_id(db_session: AsyncSession, project_name: str) -> str:
    project = (
        await db_session.execute(
            select(CanonicalProject).where(CanonicalProject.project_name == project_name)
        )
    ).scalar_one()
    return str(project.id)


async def _acquire_and_forecast(client: AsyncClient, project_id: str, headers: dict) -> None:
    await client.post(f"/projects/{project_id}/acquire", headers=headers)
    await client.post(f"/projects/{project_id}/forecast", headers=headers)


async def _bear_year1_price(client: AsyncClient, project_id: str, headers: dict) -> float:
    resp = await client.post(f"/projects/{project_id}/scenarios", headers=headers)
    assert resp.status_code == 200
    results = (await client.get(f"/projects/{project_id}/scenario-results", headers=headers)).json()
    bear = max((r for r in results if r["scenario_type"] == "bear"), key=lambda r: r["created_at"])
    year1 = next(h for h in bear["output"]["pricing"]["horizons"] if h["year"] == 1)
    return year1["nominal_price_per_sqft"], bear


async def test_pending_override_does_not_affect_scenario_result(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await _acquire_and_forecast(client, project_id, headers)

    baseline_price, baseline_result = await _bear_year1_price(client, project_id, headers)
    assert baseline_result["project_override_id"] is None

    override_resp = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=headers,
        json={
            "adjustments": {"pricing_growth_delta_pct": -15.0},
            "reason": "First-time developer in an oversupplied micro-market",
        },
    )
    assert override_resp.status_code == 200
    assert override_resp.json()["approved"] is None

    after_price, after_result = await _bear_year1_price(client, project_id, headers)
    assert after_price == baseline_price  # unreviewed proposal must not move the numbers
    assert after_result["project_override_id"] is None


async def test_approved_override_changes_only_the_overridden_scenario_type(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await _acquire_and_forecast(client, project_id, analyst_headers)

    baseline_bear_price, _ = await _bear_year1_price(client, project_id, analyst_headers)

    await client.post(f"/projects/{project_id}/scenarios", headers=analyst_headers)
    results_resp = await client.get(f"/projects/{project_id}/scenario-results", headers=analyst_headers)
    baseline_bull = next(r for r in results_resp.json() if r["scenario_type"] == "bull")
    baseline_bull_price = next(
        h for h in baseline_bull["output"]["pricing"]["horizons"] if h["year"] == 1
    )["nominal_price_per_sqft"]

    override_resp = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=analyst_headers,
        json={
            "adjustments": {"pricing_growth_delta_pct": -15.0},
            "reason": "Harsher bear case for this deal",
        },
    )
    override_id = override_resp.json()["id"]

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)

    review_resp = await client.post(
        f"/project-scenario-overrides/{override_id}/review",
        headers=reviewer_headers,
        json={"approved": True, "notes": "Agreed given developer track record"},
    )
    assert review_resp.status_code == 200

    after_bear_price, after_bear_result = await _bear_year1_price(client, project_id, analyst_headers)
    assert after_bear_price < baseline_bear_price  # harsher override took effect
    assert after_bear_result["project_override_id"] == override_id

    results = (await client.get(f"/projects/{project_id}/scenario-results", headers=analyst_headers)).json()
    bull_after = max((r for r in results if r["scenario_type"] == "bull"), key=lambda r: r["created_at"])
    bull_after_price = next(
        h for h in bull_after["output"]["pricing"]["horizons"] if h["year"] == 1
    )["nominal_price_per_sqft"]
    assert bull_after_price == baseline_bull_price  # Bull untouched by a Bear-scoped override
    assert bull_after["project_override_id"] is None


async def test_rejected_override_never_applies_and_analyst_must_resubmit(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await _acquire_and_forecast(client, project_id, analyst_headers)
    baseline_price, _ = await _bear_year1_price(client, project_id, analyst_headers)

    override_resp = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=analyst_headers,
        json={"adjustments": {"pricing_growth_delta_pct": -15.0}, "reason": "Proposed harsher case"},
    )
    override_id = override_resp.json()["id"]

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)
    reject_resp = await client.post(
        f"/project-scenario-overrides/{override_id}/review",
        headers=reviewer_headers,
        json={"approved": False, "notes": "Too severe given the developer's actual track record"},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["approved"] is False

    unchanged_price, unchanged_result = await _bear_year1_price(client, project_id, analyst_headers)
    assert unchanged_price == baseline_price
    assert unchanged_result["project_override_id"] is None

    # Correction is a new proposal, not a mutation of the rejected one.
    resubmit_resp = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=analyst_headers,
        json={"adjustments": {"pricing_growth_delta_pct": -6.0}, "reason": "Toned-down resubmission"},
    )
    assert resubmit_resp.status_code == 200
    assert resubmit_resp.json()["version"] == 2

    approve_resp = await client.post(
        f"/project-scenario-overrides/{resubmit_resp.json()['id']}/review",
        headers=reviewer_headers,
        json={"approved": True, "notes": "This one's reasonable"},
    )
    assert approve_resp.status_code == 200

    final_price, final_result = await _bear_year1_price(client, project_id, analyst_headers)
    assert final_price < baseline_price
    assert final_result["project_override_id"] == resubmit_resp.json()["id"]


async def test_resubmitting_retires_prior_pending_proposal(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await _acquire_and_forecast(client, project_id, analyst_headers)

    first = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=analyst_headers,
        json={"adjustments": {"pricing_growth_delta_pct": -10.0}, "reason": "First proposal"},
    )
    second = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=analyst_headers,
        json={"adjustments": {"pricing_growth_delta_pct": -8.0}, "reason": "Revised proposal"},
    )
    assert second.json()["version"] == 2

    overrides_resp = await client.get(f"/projects/{project_id}/scenario-overrides", headers=analyst_headers)
    assert len(overrides_resp.json()) == 2

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)

    # The superseded first proposal can no longer be reviewed.
    resp = await client.post(
        f"/project-scenario-overrides/{first.json()['id']}/review",
        headers=reviewer_headers,
        json={"approved": True, "notes": None},
    )
    assert resp.status_code == 400


async def test_override_requires_scenario_override_permission(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    await _promote_to_reviewer(db_session, unique_email, exclusive=True)
    project_id = await _project_id(db_session, "Lodha Park")

    resp = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=headers,
        json={"adjustments": {"pricing_growth_delta_pct": -5.0}, "reason": "test"},
    )
    assert resp.status_code == 403


async def test_review_requires_review_permission_not_self_review(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")

    override_resp = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=analyst_headers,
        json={"adjustments": {"pricing_growth_delta_pct": -5.0}, "reason": "test"},
    )
    override_id = override_resp.json()["id"]

    resp = await client.post(
        f"/project-scenario-overrides/{override_id}/review",
        headers=analyst_headers,
        json={"approved": True, "notes": None},
    )
    assert resp.status_code == 403


async def test_review_is_one_time_sign_off(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")

    override_resp = await client.post(
        f"/projects/{project_id}/scenarios/bear/override",
        headers=analyst_headers,
        json={"adjustments": {"pricing_growth_delta_pct": -5.0}, "reason": "test"},
    )
    override_id = override_resp.json()["id"]

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)

    first = await client.post(
        f"/project-scenario-overrides/{override_id}/review",
        headers=reviewer_headers,
        json={"approved": True, "notes": "ok"},
    )
    assert first.status_code == 200

    second = await client.post(
        f"/project-scenario-overrides/{override_id}/review",
        headers=reviewer_headers,
        json={"approved": False, "notes": "changed my mind"},
    )
    assert second.status_code == 400


async def test_override_unknown_project_returns_404(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)
    resp = await client.post(
        "/projects/00000000-0000-0000-0000-000000000000/scenarios/bear/override",
        headers=headers,
        json={"adjustments": {"pricing_growth_delta_pct": -5.0}, "reason": "test"},
    )
    assert resp.status_code == 404
