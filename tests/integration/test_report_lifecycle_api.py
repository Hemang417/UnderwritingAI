import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.models import AcquisitionRun, ConflictResolutionLog, DataPoint, ManualOverrideDetail
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
    await db_session.execute(update(Report).values(current_version_id=None))
    await db_session.execute(delete(ReportSection))
    await db_session.execute(delete(ReportVersion))
    await db_session.execute(delete(Report))
    await db_session.execute(delete(ProjectScenarioOverride))
    await db_session.execute(delete(ScenarioResult))
    await db_session.execute(delete(ForecastRun))
    await db_session.execute(delete(ManualOverrideDetail))
    await db_session.execute(delete(ConflictResolutionLog))
    await db_session.execute(delete(DataPoint))
    await db_session.execute(delete(AcquisitionRun))
    await db_session.commit()
    yield
    app.dependency_overrides[get_llm_provider] = lambda: FixtureLLMProvider()


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "Lifecycle Tester", "password": "correct-horse-1"},
    )
    resp = await client.post("/auth/login", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _promote_to_reviewer(db_session: AsyncSession, email: str, *, exclusive: bool = False) -> None:
    user = await identity_repository.get_user_by_email(db_session, email)
    reviewer_role = await identity_repository.get_role_by_name(db_session, "reviewer")
    if exclusive:
        # Registration always grants "analyst" by default; strip it so this
        # account is reviewer-only, for tests proving an endpoint truly
        # requires a permission analysts don't have.
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


async def _acquire_and_generate(client: AsyncClient, project_id: str, headers: dict) -> dict:
    await client.post(f"/projects/{project_id}/acquire", headers=headers)
    resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": False}
    )
    assert resp.status_code == 200
    return resp.json()


async def test_full_lifecycle_draft_to_published_with_downloadable_pdf(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    version = await _acquire_and_generate(client, project_id, analyst_headers)
    assert version["status"] == "draft"

    submit_resp = await client.post(
        f"/report-versions/{version['id']}/submit", headers=analyst_headers
    )
    assert submit_resp.status_code == 200
    assert submit_resp.json()["status"] == "in_review"

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)

    review_resp = await client.post(
        f"/report-versions/{version['id']}/review",
        headers=reviewer_headers,
        json={"approved": True, "comments": "Looks good"},
    )
    assert review_resp.status_code == 200
    published = review_resp.json()
    assert published["status"] == "published"
    assert published["has_pdf"] is True
    assert published["published_by"] is not None
    assert published["reviewed_by"] is not None

    pdf_resp = await client.get(f"/report-versions/{version['id']}/pdf", headers=analyst_headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")
    assert len(pdf_resp.content) > 500


async def test_reject_sends_back_to_draft_with_comments(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    version = await _acquire_and_generate(client, project_id, analyst_headers)
    await client.post(f"/report-versions/{version['id']}/submit", headers=analyst_headers)

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)

    resp = await client.post(
        f"/report-versions/{version['id']}/review",
        headers=reviewer_headers,
        json={"approved": False, "comments": "Pricing section needs more detail"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "draft"
    assert body["review_comments"] == "Pricing section needs more detail"
    assert body["has_pdf"] is False


async def test_edit_reruns_guardrail_and_preserves_original_generated_text(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    version = await _acquire_and_generate(client, project_id, headers)
    conclusion = next(s for s in version["sections"] if s["section_name"] == "conclusion")
    assert conclusion["guardrail_status"] == "passed"
    original_text = conclusion["generated_text"]

    corrupted_text = original_text + " An extra unverified figure of 987654.0 was added."
    resp = await client.patch(
        f"/report-versions/{version['id']}/sections/{conclusion['id']}",
        headers=headers,
        json={"text": corrupted_text},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated_text"] == original_text  # untouched, per "overlay preserves original text"
    assert body["edited_text"] == corrupted_text
    assert body["guardrail_status"] == "passed"  # original generation-time result, unchanged
    assert body["edited_guardrail_status"] == "failed"
    assert body["effective_text"] == corrupted_text
    assert body["effective_guardrail_status"] == "failed"


async def test_edit_only_allowed_while_draft(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    version = await _acquire_and_generate(client, project_id, headers)
    section = version["sections"][0]

    await client.post(f"/report-versions/{version['id']}/submit", headers=headers)

    resp = await client.patch(
        f"/report-versions/{version['id']}/sections/{section['id']}",
        headers=headers,
        json={"text": "trying to edit after submission"},
    )
    assert resp.status_code == 400


async def test_submit_blocked_by_unacknowledged_edit_guardrail_failure_then_acknowledged(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    version = await _acquire_and_generate(client, project_id, headers)
    conclusion = next(s for s in version["sections"] if s["section_name"] == "conclusion")

    await client.patch(
        f"/report-versions/{version['id']}/sections/{conclusion['id']}",
        headers=headers,
        json={"text": "A fabricated number 987654.0 appears here."},
    )

    blocked = await client.post(f"/report-versions/{version['id']}/submit", headers=headers)
    assert blocked.status_code == 409
    assert conclusion["section_name"] in blocked.json()["detail"]["sections"]

    ack_resp = await client.post(
        f"/report-versions/{version['id']}/sections/{conclusion['id']}/acknowledge",
        headers=headers,
        json={"note": "Intentional approximate figure, confirmed with analyst judgment"},
    )
    assert ack_resp.status_code == 200
    assert ack_resp.json()["guardrail_acknowledged_by"] is not None

    allowed = await client.post(f"/report-versions/{version['id']}/submit", headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "in_review"


async def test_published_version_is_rejected_at_api_and_db_level(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    version = await _acquire_and_generate(client, project_id, analyst_headers)
    await client.post(f"/report-versions/{version['id']}/submit", headers=analyst_headers)

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)
    await client.post(
        f"/report-versions/{version['id']}/review",
        headers=reviewer_headers,
        json={"approved": True, "comments": None},
    )

    section = version["sections"][0]
    api_resp = await client.patch(
        f"/report-versions/{version['id']}/sections/{section['id']}",
        headers=analyst_headers,
        json={"text": "attempting to edit a published report"},
    )
    assert api_resp.status_code == 400

    with pytest.raises(Exception, match="published and immutable"):
        await db_session.execute(
            text("UPDATE report_versions SET llm_provider = 'hacked' WHERE id = :id"),
            {"id": version["id"]},
        )
    await db_session.rollback()


async def test_regeneration_after_publish_creates_new_version_and_never_touches_the_published_one(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    v1 = await _acquire_and_generate(client, project_id, analyst_headers)
    await client.post(f"/report-versions/{v1['id']}/submit", headers=analyst_headers)

    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email)
    await client.post(
        f"/report-versions/{v1['id']}/review",
        headers=reviewer_headers,
        json={"approved": True, "comments": None},
    )

    v2_resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=analyst_headers, json={"force_override": False}
    )
    assert v2_resp.status_code == 200
    v2 = v2_resp.json()
    assert v2["version_number"] == 2
    assert v2["supersedes_version_id"] == v1["id"]

    v1_after = (await client.get(f"/report-versions/{v1['id']}", headers=analyst_headers)).json()
    assert v1_after["status"] == "published"  # untouched, forever
    assert v1_after["has_pdf"] is True


async def test_compare_versions_reflects_a_real_data_change(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    v1 = await _acquire_and_generate(client, project_id, headers)

    override_resp = await client.post(
        f"/projects/{project_id}/data-points/current_price_per_sqft/override",
        headers=headers,
        json={"value": 20000, "reason": "Updated per latest price list"},
    )
    assert override_resp.status_code == 200

    v2_resp = await client.post(
        f"/projects/{project_id}/reports/generate", headers=headers, json={"force_override": False}
    )
    v2 = v2_resp.json()

    compare_resp = await client.get(f"/report-versions/{v1['id']}/compare/{v2['id']}", headers=headers)
    assert compare_resp.status_code == 200
    body = compare_resp.json()
    price_diff = next(
        d for d in body["changed_values"] if d["path"] == "/data_points/current_price_per_sqft/value"
    )
    assert price_diff["from_value"] == 18500.0
    assert price_diff["to_value"] == 20000.0
    assert any(d["changed"] for d in body["section_diffs"])


async def test_edit_requires_report_edit_draft_permission(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    reviewer_email = f"reviewer-{unique_email}"
    reviewer_headers = await _auth_headers(client, reviewer_email)
    await _promote_to_reviewer(db_session, reviewer_email, exclusive=True)

    analyst_headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    version = await _acquire_and_generate(client, project_id, analyst_headers)
    section = version["sections"][0]

    resp = await client.patch(
        f"/report-versions/{version['id']}/sections/{section['id']}",
        headers=reviewer_headers,
        json={"text": "reviewer trying to edit content directly"},
    )
    assert resp.status_code == 403


async def test_review_requires_permission_analyst_cannot_self_review(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    version = await _acquire_and_generate(client, project_id, headers)
    await client.post(f"/report-versions/{version['id']}/submit", headers=headers)

    resp = await client.post(
        f"/report-versions/{version['id']}/review",
        headers=headers,
        json={"approved": True, "comments": None},
    )
    assert resp.status_code == 403
