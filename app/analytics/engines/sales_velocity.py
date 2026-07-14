import math

from app.analytics.engines.base import InsufficientDataError

ENGINE_VERSION = "1.0.0"

"""Sales Velocity Forecast Engine (PRD 12.2).

Inputs: unit_count (DataPoint), units_sold_to_date (optional -- 0 if
unknown, e.g. no quarterly-report field has supplied it yet), assumptions
(monthly absorption rate, sell-through threshold, forecast horizons).
Outputs: cumulative units sold, inventory remaining, absorption %, at each
horizon year; sell-through timeline in months.
Dependencies: none (base engine).
Model: geometric decay of remaining inventory. remaining(t) =
remaining_at_start * (1 - monthly_rate)^t, t in months. Sell-through month
solved analytically: remaining_at_start*(1-r)^t = threshold*unit_count.
Validation: unit_count must be positive; units_sold_to_date within
[0, unit_count].
Failure modes: invalid unit_count/units_sold_to_date -> InsufficientDataError.
"""


def calculate(*, unit_count: float, assumptions: dict, units_sold_to_date: float = 0.0) -> dict:
    if unit_count is None or unit_count <= 0:
        raise InsufficientDataError("unit_count must be a positive number")
    if units_sold_to_date < 0 or units_sold_to_date > unit_count:
        raise InsufficientDataError("units_sold_to_date must be between 0 and unit_count")

    monthly_rate = assumptions["monthly_absorption_rate_pct"] / 100
    threshold_pct = assumptions["sell_through_threshold_pct"] / 100
    horizons = assumptions["horizons_years"]

    remaining_at_start = unit_count - units_sold_to_date

    horizon_forecasts = []
    for year in horizons:
        months = year * 12
        remaining = remaining_at_start * ((1 - monthly_rate) ** months)
        units_sold_cumulative = unit_count - remaining
        horizon_forecasts.append(
            {
                "year": year,
                "units_sold_cumulative": round(units_sold_cumulative, 2),
                "inventory_remaining": round(remaining, 2),
                "absorption_pct": round((units_sold_cumulative / unit_count) * 100, 2),
            }
        )

    sell_through_months = None
    if monthly_rate > 0 and remaining_at_start > 0:
        target_remaining = unit_count * threshold_pct
        if remaining_at_start <= target_remaining:
            sell_through_months = 0.0
        else:
            sell_through_months = math.log(target_remaining / remaining_at_start) / math.log(1 - monthly_rate)

    sell_through_out = round(sell_through_months, 1) if sell_through_months is not None else None

    return {
        "engine_version": ENGINE_VERSION,
        "unit_count": unit_count,
        "units_sold_to_date": units_sold_to_date,
        "monthly_absorption_rate_pct": assumptions["monthly_absorption_rate_pct"],
        "sell_through_timeline_months": sell_through_out,
        "horizons": horizon_forecasts,
    }
