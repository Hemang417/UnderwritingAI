from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.models import (
    AcquisitionRun,
    ConflictResolutionLog,
    DataPoint,
    DataSource,
    Document,
    OCRJob,
)
from app.discovery.models import CanonicalProject

pytestmark = pytest.mark.asyncio

FIXTURE_SCAN = Path(__file__).resolve().parent.parent / "fixtures" / "lodha_park_quarterly_report_scan.jpg"


@pytest_asyncio.fixture(autouse=True)
async def _reset_acquisition_state(db_session: AsyncSession):
    await db_session.execute(delete(ConflictResolutionLog))
    await db_session.execute(delete(DataPoint))
    await db_session.execute(delete(OCRJob))
    await db_session.execute(delete(Document))
    await db_session.execute(delete(AcquisitionRun))
    await db_session.commit()
    yield


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "OCR Tester", "password": "correct-horse-1"},
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


async def _maha_rera_source_id(db_session: AsyncSession) -> str:
    source = (
        await db_session.execute(select(DataSource).where(DataSource.adapter_key == "maha_rera"))
    ).scalar_one()
    return str(source.id)


async def test_ingested_scan_has_lower_confidence_than_clean_fetch_for_same_fact(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)
    maha_rera_id = await _maha_rera_source_id(db_session)

    # Clean structured fetch first (M2 path) -- unit_count=450, composite=95.
    clean_resp = await client.post(f"/projects/{project_id}/acquire", headers=headers)
    assert clean_resp.status_code == 200

    clean_points_before = await client.get(f"/projects/{project_id}/data-points", headers=headers)
    clean_unit_count = next(
        d
        for d in clean_points_before.json()
        if d["field_name"] == "unit_count" and d["source_name"] == "MahaRERA"
    )
    assert clean_unit_count["composite_confidence"] == 95.0
    assert clean_unit_count["ocr_confidence"] is None

    # Now ingest the real scanned quarterly report for the same project/source.
    with open(FIXTURE_SCAN, "rb") as f:
        ingest_resp = await client.post(
            f"/projects/{project_id}/documents",
            headers=headers,
            files={"file": ("quarterly_report.jpg", f, "image/jpeg")},
            data={"data_source_id": maha_rera_id, "doc_type": "quarterly_progress_report"},
        )
    assert ingest_resp.status_code == 200
    ingest_body = ingest_resp.json()
    assert "unit_count" in ingest_body["fields_written"]
    assert 0 < ingest_body["ocr_confidence"] < 100

    data_points = (await client.get(f"/projects/{project_id}/data-points", headers=headers)).json()
    unit_count_points = [
        d for d in data_points if d["field_name"] == "unit_count" and d["source_name"] == "MahaRERA"
    ]
    assert len(unit_count_points) == 2  # the clean fetch (now superseded) + the OCR'd one

    ocr_point = next(d for d in unit_count_points if d["ocr_confidence"] is not None)
    superseded_point = next(d for d in unit_count_points if d["ocr_confidence"] is None)

    assert ocr_point["value"] == 450  # OCR read the real fixture image correctly
    assert ocr_point["is_current"] is True
    assert ocr_point["status"] == "active"
    assert ocr_point["extraction_confidence"] is not None
    # The actual point of M3: a real scanned document, correctly, produces
    # lower composite confidence than a clean structured fetch of the exact
    # same fact -- not asserted against a mock, against the real fixture.
    assert ocr_point["composite_confidence"] < superseded_point["composite_confidence"]
    assert superseded_point["status"] == "superseded"
    assert superseded_point["composite_confidence"] == 95.0


async def test_ingest_unknown_project_returns_404(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    maha_rera_id = await _maha_rera_source_id(db_session)

    with open(FIXTURE_SCAN, "rb") as f:
        resp = await client.post(
            "/projects/00000000-0000-0000-0000-000000000000/documents",
            headers=headers,
            files={"file": ("scan.jpg", f, "image/jpeg")},
            data={"data_source_id": maha_rera_id, "doc_type": "quarterly_progress_report"},
        )
    assert resp.status_code == 404


async def test_ingest_unknown_data_source_returns_404(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)

    with open(FIXTURE_SCAN, "rb") as f:
        resp = await client.post(
            f"/projects/{project_id}/documents",
            headers=headers,
            files={"file": ("scan.jpg", f, "image/jpeg")},
            data={
                "data_source_id": "00000000-0000-0000-0000-000000000000",
                "doc_type": "quarterly_progress_report",
            },
        )
    assert resp.status_code == 404


async def test_stale_flag_fires_for_old_data_and_not_for_fresh_data(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _lodha_park_id(db_session)

    await client.post(f"/projects/{project_id}/acquire", headers=headers)

    # unit_count has a 180-day staleness threshold (field_catalog) -- push
    # this DataPoint's fetched_at back past that window directly, since
    # nothing in the app naturally produces year-old data in a test run.
    dp = (
        await db_session.execute(
            select(DataPoint).where(DataPoint.field_name == "unit_count", DataPoint.is_current.is_(True))
        )
    ).scalar_one()
    dp.fetched_at = datetime.now(UTC) - timedelta(days=200)
    await db_session.commit()

    data_points = (await client.get(f"/projects/{project_id}/data-points", headers=headers)).json()
    unit_count = next(d for d in data_points if d["field_name"] == "unit_count" and d["is_current"])
    possession_date = next(d for d in data_points if d["field_name"] == "possession_date" and d["is_current"])

    assert unit_count["is_stale"] is True
    assert possession_date["is_stale"] is False  # untouched, still fresh
