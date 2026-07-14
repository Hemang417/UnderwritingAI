import pytest

from app.analytics.engines import pricing
from app.analytics.engines.base import InsufficientDataError

ASSUMPTIONS = {
    "annual_appreciation_rate_pct": 8.0,
    "annual_inflation_rate_pct": 5.5,
    "developer_premium_pct": 0.0,
    "infrastructure_impact_pct": 0.0,
    "horizons_years": [1, 3, 5, 7, 10],
}


def test_year_one_nominal_price_matches_simple_compounding():
    result = pricing.calculate(current_price_per_sqft=18500, assumptions=ASSUMPTIONS)
    year_one = next(h for h in result["horizons"] if h["year"] == 1)
    assert year_one["nominal_price_per_sqft"] == round(18500 * 1.08, 2)


def test_real_price_is_always_less_than_or_equal_to_nominal_when_inflation_positive():
    result = pricing.calculate(current_price_per_sqft=18500, assumptions=ASSUMPTIONS)
    for horizon in result["horizons"]:
        assert horizon["real_price_per_sqft"] <= horizon["nominal_price_per_sqft"]


def test_developer_premium_and_infrastructure_impact_increase_effective_rate():
    boosted = dict(ASSUMPTIONS, developer_premium_pct=2.0, infrastructure_impact_pct=1.0)
    result = pricing.calculate(current_price_per_sqft=18500, assumptions=boosted)
    assert result["effective_annual_appreciation_rate_pct"] == 11.0  # 8 + 2 + 1


def test_calculation_is_deterministic():
    first = pricing.calculate(current_price_per_sqft=18500, assumptions=ASSUMPTIONS)
    second = pricing.calculate(current_price_per_sqft=18500, assumptions=ASSUMPTIONS)
    assert first == second


@pytest.mark.parametrize("bad_price", [0, -100, None])
def test_non_positive_or_missing_price_raises_insufficient_data(bad_price):
    with pytest.raises(InsufficientDataError):
        pricing.calculate(current_price_per_sqft=bad_price, assumptions=ASSUMPTIONS)
