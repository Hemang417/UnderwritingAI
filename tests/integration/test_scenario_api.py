import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.models import AcquisitionRun, ConflictResolutionLog, DataPoint
from app.analytics.models import ForecastRun
from app.discovery.models import CanonicalProject
from app.scenario.models import ScenarioAssumptionSet, ScenarioResult, ScenarioType

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_state(db_session: AsyncSession):
    await db_session.execute(delete(ScenarioResult))
    await db_session.execute(delete(ForecastRun))
    await db_session.execute(delete(ConflictResolutionLog))
    await db_session.execute(delete(DataPoint))
    await db_session.execute(delete(AcquisitionRun))
    await db_session.commit()
    yield


async def _auth_headers(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": "Scenario Tester", "password": "correct-horse-1"},
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
    resp = await client.post(f"/projects/{project_id}/forecast", headers=headers)
    assert resp.status_code == 200


async def test_scenarios_require_a_prior_successful_forecast(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")  # never acquired/forecast

    resp = await client.post(f"/projects/{project_id}/scenarios", headers=headers)
    assert resp.status_code == 200
    statuses = {r["scenario_type"]: r["status"] for r in resp.json()["runs"]}
    assert statuses == {"bear": "insufficient_data", "base": "insufficient_data", "bull": "insufficient_data"}


async def test_bear_base_bull_produce_ordered_pricing_and_risk_outcomes(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await _acquire_and_forecast(client, project_id, headers)

    resp = await client.post(f"/projects/{project_id}/scenarios", headers=headers)
    assert resp.status_code == 200
    statuses = {r["scenario_type"]: r["status"] for r in resp.json()["runs"]}
    assert statuses == {"bear": "success", "base": "success", "bull": "success"}

    results_resp = await client.get(f"/projects/{project_id}/scenario-results", headers=headers)
    assert results_resp.status_code == 200
    results = results_resp.json()
    assert len(results) == 3

    by_type = {r["scenario_type"]: r["output"] for r in results}

    # Base reproduces the un-adjusted forecast (identity scenario, no deltas).
    base_year1 = next(h for h in by_type["base"]["pricing"]["horizons"] if h["year"] == 1)
    bear_year1 = next(h for h in by_type["bear"]["pricing"]["horizons"] if h["year"] == 1)
    bull_year1 = next(h for h in by_type["bull"]["pricing"]["horizons"] if h["year"] == 1)

    # Bear < Base < Bull on nominal price, given the seeded deltas.
    assert bear_year1["nominal_price_per_sqft"] < base_year1["nominal_price_per_sqft"]
    assert base_year1["nominal_price_per_sqft"] < bull_year1["nominal_price_per_sqft"]

    # Risk composite: Bear should be riskier (higher score) than Bull.
    assert by_type["bear"]["risk"]["composite_risk_score"] > by_type["bull"]["risk"]["composite_risk_score"]

    # base_forecast_run_ids pin all four underlying engine runs.
    expected_engines = {"pricing", "sales_velocity", "financial", "risk"}
    assert set(results[0]["base_forecast_run_ids"].keys()) == expected_engines


async def test_rerunning_scenarios_with_unchanged_inputs_is_deterministic(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await _acquire_and_forecast(client, project_id, headers)

    await client.post(f"/projects/{project_id}/scenarios", headers=headers)
    first = (await client.get(f"/projects/{project_id}/scenario-results", headers=headers)).json()

    await client.post(f"/projects/{project_id}/scenarios", headers=headers)
    second = (await client.get(f"/projects/{project_id}/scenario-results", headers=headers)).json()

    assert len(second) == 6  # 3 scenarios x 2 runs -- nothing overwritten

    def latest_output_by_type(results: list[dict]) -> dict:
        latest: dict[str, dict] = {}
        for r in results:
            latest.setdefault(r["scenario_type"], r["output"])
        return latest

    first_by_type = latest_output_by_type(first)
    second_by_type = latest_output_by_type(second)
    for scenario_type in ("bear", "base", "bull"):
        assert second_by_type[scenario_type] == first_by_type[scenario_type], (
            f"{scenario_type} changed on rerun"
        )


async def test_changing_scenario_assumption_set_config_changes_result_with_no_code_change(
    client: AsyncClient, db_session: AsyncSession, unique_email: str
):
    """This is M6's documented 'done' criterion: changing an assumption
    set's config value changes ScenarioResult deterministically and
    traceably with no code change."""
    headers = await _auth_headers(client, unique_email)
    project_id = await _project_id(db_session, "Lodha Park")
    await _acquire_and_forecast(client, project_id, headers)

    await client.post(f"/projects/{project_id}/scenarios", headers=headers)
    before = (await client.get(f"/projects/{project_id}/scenario-results", headers=headers)).json()
    bear_before = next(r for r in before if r["scenario_type"] == "bear")

    # Admin-style config change: version the active Bear assumption set with
    # a much harsher pricing_growth_delta_pct. No application code touched.
    active_bear = (
        await db_session.execute(
            select(ScenarioAssumptionSet).where(
                ScenarioAssumptionSet.scenario_type == ScenarioType.BEAR,
                ScenarioAssumptionSet.is_active.is_(True),
            )
        )
    ).scalar_one()
    active_bear.is_active = False
    new_adjustments = dict(active_bear.adjustments, pricing_growth_delta_pct=-15.0)
    db_session.add(
        ScenarioAssumptionSet(
            scenario_type=ScenarioType.BEAR,
            version=active_bear.version + 1,
            name="Bear Case (severe)",
            adjustments=new_adjustments,
            is_active=True,
        )
    )
    await db_session.commit()
    db_session.expire_all()

    await client.post(f"/projects/{project_id}/scenarios", headers=headers)
    after = (await client.get(f"/projects/{project_id}/scenario-results", headers=headers)).json()
    bear_after = max(
        (r for r in after if r["scenario_type"] == "bear"), key=lambda r: r["created_at"]
    )

    before_price = next(h for h in bear_before["output"]["pricing"]["horizons"] if h["year"] == 1)[
        "nominal_price_per_sqft"
    ]
    after_price = next(h for h in bear_after["output"]["pricing"]["horizons"] if h["year"] == 1)[
        "nominal_price_per_sqft"
    ]
    assert after_price < before_price  # harsher config -> lower forecast price, purely from data
