import pytest

from app.analytics.engines import sales_velocity
from app.analytics.engines.base import InsufficientDataError

ASSUMPTIONS = {
    "monthly_absorption_rate_pct": 2.0,
    "sell_through_threshold_pct": 5.0,
    "horizons_years": [1, 3, 5, 7, 10],
}


def test_units_sold_and_inventory_remaining_always_sum_to_total():
    result = sales_velocity.calculate(unit_count=450, assumptions=ASSUMPTIONS)
    for horizon in result["horizons"]:
        assert horizon["units_sold_cumulative"] + horizon["inventory_remaining"] == pytest.approx(450)


def test_absorption_increases_monotonically_with_year():
    result = sales_velocity.calculate(unit_count=450, assumptions=ASSUMPTIONS)
    absorptions = [h["absorption_pct"] for h in result["horizons"]]
    assert absorptions == sorted(absorptions)


def test_units_sold_to_date_reduces_starting_inventory():
    fresh = sales_velocity.calculate(unit_count=450, assumptions=ASSUMPTIONS, units_sold_to_date=0)
    partially_sold = sales_velocity.calculate(unit_count=450, assumptions=ASSUMPTIONS, units_sold_to_date=100)
    fresh_year_1 = next(h for h in fresh["horizons"] if h["year"] == 1)
    partial_year_1 = next(h for h in partially_sold["horizons"] if h["year"] == 1)
    assert partial_year_1["units_sold_cumulative"] > fresh_year_1["units_sold_cumulative"]


def test_zero_absorption_never_sells_through():
    zero_rate = dict(ASSUMPTIONS, monthly_absorption_rate_pct=0.0)
    result = sales_velocity.calculate(unit_count=450, assumptions=zero_rate)
    assert result["sell_through_timeline_months"] is None
    assert all(h["units_sold_cumulative"] == 0 for h in result["horizons"])


def test_calculation_is_deterministic():
    first = sales_velocity.calculate(unit_count=450, assumptions=ASSUMPTIONS)
    second = sales_velocity.calculate(unit_count=450, assumptions=ASSUMPTIONS)
    assert first == second


def test_non_positive_unit_count_raises_insufficient_data():
    with pytest.raises(InsufficientDataError):
        sales_velocity.calculate(unit_count=0, assumptions=ASSUMPTIONS)


def test_units_sold_to_date_exceeding_unit_count_raises_insufficient_data():
    with pytest.raises(InsufficientDataError):
        sales_velocity.calculate(unit_count=450, assumptions=ASSUMPTIONS, units_sold_to_date=500)
