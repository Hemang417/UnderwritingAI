from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition import repository as acquisition_repository
from app.acquisition.models import DataPoint
from app.analytics import repository as analytics_repository
from app.analytics.models import EngineType, ForecastRunStatus
from app.discovery.models import CanonicalProject
from app.reporting.gating import ENTITY_TYPE, REQUIRED_FIELDS
from app.scenario import repository as scenario_repository
from app.scenario.models import ScenarioType

"""Report Assembly Service (SAD S12 "Report JSON discipline"): builds and
freezes `ReportVersion.generated_json` *before* any LLM call. All derived
figures are precomputed by the Analytics/Scenario engines and included
explicitly here -- the LLM is never expected to compute anything, which is
what keeps the guardrail a pure presence-check rather than a math checker.
"""


def _typed_value(data_point: DataPoint):
    if data_point.value_date is not None:
        return data_point.value_date.isoformat()
    if data_point.value_numeric is not None:
        return data_point.value_numeric
    if data_point.value_text is not None:
        return data_point.value_text
    return data_point.value_json


async def _data_point_json(session: AsyncSession, data_point: DataPoint) -> dict:
    out = {
        "value": _typed_value(data_point),
        "source": data_point.source.name,
        "confidence": data_point.composite_confidence,
        "effective_date": data_point.effective_date.isoformat() if data_point.effective_date else None,
    }

    # ADR-016: a conflict resolved for calculation purposes doesn't mean the
    # disagreement disappears from what the IC sees -- disclose the
    # rejected value + source + rule alongside the resolved one. MVP
    # simplification, documented not hidden: only the first logged loser is
    # disclosed (the current adapter set never has more than two competing
    # sources per field).
    conflict_logs = await acquisition_repository.list_conflict_logs_for_winner(session, data_point.id)
    if conflict_logs:
        log = conflict_logs[0]
        loser = await acquisition_repository.get_data_point_by_id(session, log.losing_data_point_id)
        out["discrepancy"] = {
            "resolved_value": out["value"],
            "resolved_source": data_point.source.name,
            "rejected_value": _typed_value(loser),
            "rejected_source": loser.source.name,
            "rule_applied": log.rule_applied,
        }

    return out


async def assemble_report_json(session: AsyncSession, *, project: CanonicalProject) -> dict:
    data_points: dict[str, dict] = {}
    for field_name in REQUIRED_FIELDS:
        data_point = await acquisition_repository.get_current_data_point(
            session, entity_type=ENTITY_TYPE, entity_id=project.id, field_name=field_name
        )
        if data_point is not None:
            data_points[field_name] = await _data_point_json(session, data_point)

    forecast_runs = await analytics_repository.list_forecast_runs_for_project(session, project.id)
    forecasts: dict[str, dict] = {}
    for engine_type in (EngineType.PRICING, EngineType.SALES_VELOCITY, EngineType.FINANCIAL, EngineType.RISK):
        # list_forecast_runs_for_project is ordered (engine_type, created_at
        # desc), so the first match per engine_type is its latest run.
        latest = next((r for r in forecast_runs if r.engine_type == engine_type), None)
        if latest is not None and latest.status == ForecastRunStatus.SUCCESS:
            forecasts[engine_type.value] = latest.output

    scenario_results = await scenario_repository.list_scenario_results_for_project(session, project.id)
    scenarios: dict[str, dict] = {}
    for scenario_type in (ScenarioType.BEAR, ScenarioType.BASE, ScenarioType.BULL):
        latest = next(
            (r for r in scenario_results if r.scenario_assumption_set.scenario_type == scenario_type), None
        )
        if latest is not None and latest.status == ForecastRunStatus.SUCCESS:
            scenarios[scenario_type.value] = latest.output

    return {
        "project": {
            "project_name": project.project_name,
            "developer": project.developer.name,
            "city": project.city,
            "locality": project.locality,
            "state": project.state,
            "rera_registration_number": project.rera_registration_number,
            "status": project.status,
        },
        "data_points": data_points,
        "forecasts": forecasts,
        "scenarios": scenarios,
    }


def _slice_full(data: dict) -> dict:
    return data


def _slice_project_overview(data: dict) -> dict:
    return {"project": data["project"], "data_points": data["data_points"]}


def _slice_developer_analysis(data: dict) -> dict:
    risk = data["forecasts"].get("risk", {})
    return {
        "developer": data["project"]["developer"],
        "risk_developer_category_score": risk.get("category_scores", {}).get("developer"),
        "risk_developer_explanation": risk.get("category_explanations", {}).get("developer"),
    }


def _slice_market_analysis(data: dict) -> dict:
    risk = data["forecasts"].get("risk", {})
    return {
        "city": data["project"]["city"],
        "locality": data["project"]["locality"],
        "risk_market_category_score": risk.get("category_scores", {}).get("market"),
        "risk_market_explanation": risk.get("category_explanations", {}).get("market"),
        "risk_demand_category_score": risk.get("category_scores", {}).get("demand"),
        "risk_demand_explanation": risk.get("category_explanations", {}).get("demand"),
    }


def _slice_pricing_analysis(data: dict) -> dict:
    return {
        "current_price_per_sqft": data["data_points"].get("current_price_per_sqft"),
        "pricing_forecast": data["forecasts"].get("pricing"),
    }


def _slice_sales_velocity_analysis(data: dict) -> dict:
    return {
        "unit_count": data["data_points"].get("unit_count"),
        "sales_velocity_forecast": data["forecasts"].get("sales_velocity"),
    }


def _slice_scenario_analysis(data: dict) -> dict:
    return {
        "scenarios": data["scenarios"],
        "base_pricing_forecast": data["forecasts"].get("pricing"),
        "base_sales_velocity_forecast": data["forecasts"].get("sales_velocity"),
    }


def _slice_risk_assessment(data: dict) -> dict:
    return {"risk": data["forecasts"].get("risk")}


def _slice_key_assumptions(data: dict) -> dict:
    # The section ADR-016 exists for: every discrepancy block embedded in
    # data_points must be disclosed here explicitly, not just the resolved
    # figure.
    return {"data_points": data["data_points"]}


def _slice_investment_recommendation(data: dict) -> dict:
    return {
        "financial_forecast": data["forecasts"].get("financial"),
        "risk": data["forecasts"].get("risk"),
        "scenarios": data["scenarios"],
    }


def _slice_conclusion(data: dict) -> dict:
    return {"financial_forecast": data["forecasts"].get("financial")}


# Least-privilege prompting (SAD S12): every section but Executive Summary
# (a deliberate synthesis of the whole report) gets only the JSON it needs.
SECTION_JSON_SLICERS: dict[str, Callable[[dict], dict]] = {
    "executive_summary": _slice_full,
    "project_overview": _slice_project_overview,
    "developer_analysis": _slice_developer_analysis,
    "market_analysis": _slice_market_analysis,
    "pricing_analysis": _slice_pricing_analysis,
    "sales_velocity_analysis": _slice_sales_velocity_analysis,
    "scenario_analysis": _slice_scenario_analysis,
    "risk_assessment": _slice_risk_assessment,
    "key_assumptions": _slice_key_assumptions,
    "investment_recommendation": _slice_investment_recommendation,
    "conclusion": _slice_conclusion,
}

SECTION_NAMES: list[str] = list(SECTION_JSON_SLICERS.keys())
