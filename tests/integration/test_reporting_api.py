import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.models import AcquisitionRun, ConflictResolutionLog, DataPoint
from app.analytics.models import ForecastRun
from app.discovery.models import CanonicalProject
from app.identity import repository as identity_repository
from app.identity.models import UserRole
from app.llm.dependencies import get_llm_provider
from app.llm.fixture_provider import FixtureLLMProvider
from app.main import app
from app.reporting.models import Report, ReportSection, ReportVersion
from app.scenario.models import ProjectScenarioOverride, ScenarioResult

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_state(db_session: AsyncSession):
    # Break the circular reports.current_version_id <-> report_versions.
    # report_id reference before deleting either side.
    await db_session.execute(update(Report).values(current_version_id=None))
    await db_session.execute(delete(ReportSection))
    await db_session.execute(delete(ReportVersion))
    await db_session.execute(delete(Report))
    await db_session.execute(delete(ProjectScenarioOverride))
    await db_session.execute(delete(ScenarioResult))
    await db_session.execute(delete(ForecastRun))
    await db_session.execute(delete(ConflictResolutionLog))
    await db_session.execute(delete(DataPoint))
    await db_session.execute(delete(AcquisitionRun))
    await db_session.commit()
    yield
    app.dependency_overrides[get_llm_provider] = lambda: FixtureLLMProvider()


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "Reporting Tester", "password": "correct-horse-1"},
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


async def _acquire_and_forecast(client: AsyncClient, project_id: str, headers: dict) -> None:
    await client.post(f"/projects/{project_id}/acquire", headers=headers)
    await client.post(f"/projects/{project_id}/forecast", headers=headers)
    await client.post(f"/projects/{project_id}/scenarios", headers=headers)


async def test_full_report_generates_all_eleven_sections_to_draft(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await client.post(f"/projects/{project_id}/acquire", headers=headers)

    resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "draft"
    assert body["guardrail_status"] == "passed"
    assert body["version_number"] == 1
    assert len(body["sections"]) == 11
    assert all(s["guardrail_status"] == "passed" for s in body["sections"])
    section_names = {s["section_name"] for s in body["sections"]}
    assert section_names == {
        "executive_summary",
        "project_overview",
        "developer_analysis",
        "market_analysis",
        "pricing_analysis",
        "sales_velocity_analysis",
        "scenario_analysis",
        "risk_assessment",
        "key_assumptions",
        "investment_recommendation",
        "conclusion",
    }


async def test_completeness_gate_blocks_without_acquisition(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")  # never acquired

    resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": False}
    )
    assert resp.status_code == 409
    issues = {i["field_name"]: i["issue"] for i in resp.json()["detail"]["issues"]}
    assert issues == {
        "unit_count": "missing",
        "possession_date": "missing",
        "current_price_per_sqft": "missing",
    }

    # Nothing was created for the blocked attempt.
    list_resp = await client.get(f"/projects/{project_id}/reports", headers=headers)
    assert list_resp.json() == []


async def test_completeness_gate_force_override_proceeds_and_logs_it(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")  # never acquired

    resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["completeness_overridden"] is True
    assert len(body["completeness_issues"]) == 3
    assert len(body["sections"]) == 11  # still generates, sparsely, rather than crashing


async def test_discrepancy_is_disclosed_and_traceable_through_guardrail(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await client.post(f"/projects/{project_id}/acquire", headers=headers)  # RERA 450 vs developer site 460

    resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": False}
    )
    version_id = resp.json()["id"]

    detail = (await client.get(f"/report-versions/{version_id}", headers=headers)).json()
    unit_count = detail["generated_json"]["data_points"]["unit_count"]
    assert unit_count["discrepancy"]["resolved_value"] == 450.0
    assert unit_count["discrepancy"]["rejected_value"] == 460.0
    assert unit_count["discrepancy"]["resolved_source"] == "MahaRERA"
    assert unit_count["discrepancy"]["rejected_source"] == "Developer Website"

    key_assumptions = next(s for s in detail["sections"] if s["section_name"] == "key_assumptions")
    assert key_assumptions["guardrail_status"] == "passed"
    assert "460" in key_assumptions["generated_text"] or "460.0" in key_assumptions["generated_text"]


async def test_corrupted_section_is_caught_and_blocks_the_version(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    """The SAD/ARD-mandated negative test: an intentionally-corrupted
    section must be caught and block the ReportVersion, without silently
    dragging down sections that were never corrupted."""
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await client.post(f"/projects/{project_id}/acquire", headers=headers)

    app.dependency_overrides[get_llm_provider] = lambda: FixtureLLMProvider(
        corrupt_sections={"pricing_analysis"}
    )

    resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["guardrail_status"] == "failed"

    by_name = {s["section_name"]: s for s in body["sections"]}
    pricing = by_name["pricing_analysis"]
    assert pricing["guardrail_status"] == "failed"
    assert pricing["attempt_count"] == 3  # 1 initial + 2 bounded corrective attempts, still failing
    assert any("987654" in u["raw_text"] for u in pricing["guardrail_report"]["unmatched"])

    # Sections that were never corrupted still pass -- guardrail failure is
    # per-section, not an all-or-nothing wipeout.
    assert by_name["executive_summary"]["guardrail_status"] == "passed"
    assert by_name["conclusion"]["guardrail_status"] == "passed"


async def test_regeneration_creates_a_new_incrementing_version(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await client.post(f"/projects/{project_id}/acquire", headers=headers)

    first = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": False}
    )
    second = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": False}
    )
    assert first.json()["version_number"] == 1
    assert second.json()["version_number"] == 2
    assert first.json()["report_id"] == second.json()["report_id"]

    versions = (await client.get(f"/projects/{project_id}/reports", headers=headers)).json()
    assert [v["version_number"] for v in versions] == [2, 1]


async def test_generate_requires_report_create_permission(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    user = await identity_repository.get_user_by_email(db_session, unique_email)
    reviewer_role = await identity_repository.get_role_by_name(db_session, "reviewer")
    await db_session.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db_session.add(UserRole(user_id=user.id, role_id=reviewer_role.id))
    await db_session.commit()
    db_session.expire_all()

    project_id = await _project_id(db_session, "Lodha Park")
    resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": True}
    )
    assert resp.status_code == 403


async def test_generate_unknown_project_returns_404(client: AsyncClient, unique_email: str):
    headers = await _auth_headers(client, unique_email)
    resp = await client.post(
        "/projects/00000000-0000-0000-0000-000000000000/reports/generate",
        headers=headers,
        json={"force_override": True},
    )
    assert resp.status_code == 404
