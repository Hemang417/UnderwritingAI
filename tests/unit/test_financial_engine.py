import pytest

from app.analytics.engines import financial, pricing, sales_velocity
from app.analytics.engines.base import InsufficientDataError

PRICING_ASSUMPTIONS = {
    "annual_appreciation_rate_pct": 8.0,
    "annual_inflation_rate_pct": 5.5,
    "developer_premium_pct": 0.0,
    "infrastructure_impact_pct": 0.0,
    "horizons_years": [1, 3, 5, 7, 10],
}
SV_ASSUMPTIONS = {
    "monthly_absorption_rate_pct": 2.0,
    "sell_through_threshold_pct": 5.0,
    "horizons_years": [1, 3, 5, 7, 10],
}
FIN_ASSUMPTIONS = {
    "discount_rate_pct": 12.0,
    "average_unit_size_sqft": 650.0,
    "horizons_years": [1, 3, 5, 7, 10],
}


def _pricing_output():
    return pricing.calculate(current_price_per_sqft=18500, assumptions=PRICING_ASSUMPTIONS)


def _sv_output():
    return sales_velocity.calculate(unit_count=450, assumptions=SV_ASSUMPTIONS)


def test_discounted_revenue_never_exceeds_nominal_cumulative_revenue():
    result = financial.calculate(
        pricing_output=_pricing_output(), sales_velocity_output=_sv_output(), assumptions=FIN_ASSUMPTIONS
    )
    for horizon in result["horizons"]:
        assert horizon["discounted_cumulative_revenue"] <= horizon["cumulative_revenue"]


def test_cumulative_revenue_increases_with_year():
    result = financial.calculate(
        pricing_output=_pricing_output(), sales_velocity_output=_sv_output(), assumptions=FIN_ASSUMPTIONS
    )
    revenues = [h["cumulative_revenue"] for h in result["horizons"]]
    assert revenues == sorted(revenues)


def test_total_revenue_potential_matches_unit_count_times_terminal_price():
    p = _pricing_output()
    sv = _sv_output()
    result = financial.calculate(pricing_output=p, sales_velocity_output=sv, assumptions=FIN_ASSUMPTIONS)

    terminal_price = next(h["nominal_price_per_sqft"] for h in p["horizons"] if h["year"] == 10)
    expected = round(sv["unit_count"] * terminal_price * FIN_ASSUMPTIONS["average_unit_size_sqft"], 2)
    assert result["total_revenue_potential_at_sellout"] == expected


def test_calculation_is_deterministic():
    p, sv = _pricing_output(), _sv_output()
    first = financial.calculate(pricing_output=p, sales_velocity_output=sv, assumptions=FIN_ASSUMPTIONS)
    second = financial.calculate(pricing_output=p, sales_velocity_output=sv, assumptions=FIN_ASSUMPTIONS)
    assert first == second


def test_missing_horizon_year_in_dependency_output_raises_insufficient_data():
    p = _pricing_output()
    p["horizons"] = [h for h in p["horizons"] if h["year"] != 10]  # drop a required horizon
    with pytest.raises(InsufficientDataError):
        financial.calculate(pricing_output=p, sales_velocity_output=_sv_output(), assumptions=FIN_ASSUMPTIONS)
