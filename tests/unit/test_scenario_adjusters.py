import pytest

from app.scenario.adjusters import (
    FinancialParameterAdjuster,
    PricingParameterAdjuster,
    RiskCategoryAdjuster,
    SalesVelocityParameterAdjuster,
)

PRICING_PARAMS = {
    "annual_appreciation_rate_pct": 8.0,
    "annual_inflation_rate_pct": 5.5,
    "developer_premium_pct": 0.0,
    "infrastructure_impact_pct": 0.0,
    "horizons_years": [1, 3, 5, 7, 10],
}

SV_PARAMS = {
    "monthly_absorption_rate_pct": 2.0,
    "sell_through_threshold_pct": 5.0,
    "horizons_years": [1, 3, 5],
}

FINANCIAL_PARAMS = {"discount_rate_pct": 12.0, "average_unit_size_sqft": 650.0, "horizons_years": [1, 3, 5]}

RISK_CATEGORY_SCORES = {
    "construction": 70.0,
    "developer": 50.0,
    "market": 50.0,
    "demand": 50.0,
    "execution": 70.0,
    "pricing": 10.0,
    "regulatory": 50.0,
}


def test_empty_adjustments_leave_pricing_params_unchanged():
    result = PricingParameterAdjuster().adjust(PRICING_PARAMS, {})
    assert result == PRICING_PARAMS


def test_pricing_growth_delta_shifts_appreciation_rate_only():
    result = PricingParameterAdjuster().adjust(PRICING_PARAMS, {"pricing_growth_delta_pct": -4.0})
    assert result["annual_appreciation_rate_pct"] == 4.0
    assert result["annual_inflation_rate_pct"] == 5.5  # untouched


def test_inflation_delta_shifts_inflation_rate():
    result = PricingParameterAdjuster().adjust(PRICING_PARAMS, {"inflation_delta_pct": 1.5})
    assert result["annual_inflation_rate_pct"] == 7.0


def test_sales_velocity_multiplier_scales_absorption_rate():
    result = SalesVelocityParameterAdjuster().adjust(SV_PARAMS, {"sales_velocity_multiplier": 0.6})
    assert result["monthly_absorption_rate_pct"] == pytest.approx(1.2)


def test_sales_velocity_multiplier_default_is_identity():
    result = SalesVelocityParameterAdjuster().adjust(SV_PARAMS, {})
    assert result["monthly_absorption_rate_pct"] == SV_PARAMS["monthly_absorption_rate_pct"]


def test_interest_rate_delta_shifts_discount_rate():
    result = FinancialParameterAdjuster().adjust(FINANCIAL_PARAMS, {"interest_rate_delta_pct": 2.5})
    assert result["discount_rate_pct"] == 14.5
    assert result["average_unit_size_sqft"] == FINANCIAL_PARAMS["average_unit_size_sqft"]  # untouched


def test_risk_construction_delay_bumps_construction_and_execution():
    result = RiskCategoryAdjuster().adjust(RISK_CATEGORY_SCORES, {"construction_delay_risk_pts": 20.0})
    assert result["construction"] == 90.0
    assert result["execution"] == 90.0
    assert result["developer"] == 50.0  # different dimension, untouched


def test_risk_developer_execution_bumps_developer_category_only():
    result = RiskCategoryAdjuster().adjust(RISK_CATEGORY_SCORES, {"developer_execution_risk_pts": 15.0})
    assert result["developer"] == 65.0
    assert result["construction"] == 70.0


def test_risk_category_scores_clamp_to_0_100_range():
    high = RiskCategoryAdjuster().adjust(RISK_CATEGORY_SCORES, {"construction_delay_risk_pts": 1000.0})
    assert high["construction"] == 100.0

    low = RiskCategoryAdjuster().adjust(RISK_CATEGORY_SCORES, {"demand_risk_pts": -1000.0})
    assert low["demand"] == 0.0


def test_unrecognized_adjustment_keys_are_ignored():
    result = PricingParameterAdjuster().adjust(PRICING_PARAMS, {"some_future_dimension": 999.0})
    assert result == PRICING_PARAMS


def test_adjusters_are_deterministic():
    first = PricingParameterAdjuster().adjust(PRICING_PARAMS, {"pricing_growth_delta_pct": -4.0})
    second = PricingParameterAdjuster().adjust(PRICING_PARAMS, {"pricing_growth_delta_pct": -4.0})
    assert first == second
