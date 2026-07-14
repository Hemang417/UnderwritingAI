from app.analytics.engines.base import InsufficientDataError

ENGINE_VERSION = "1.0.0"

"""Financial Forecast Engine (PRD 12.3).

Inputs: Pricing Forecast Engine output + Sales Velocity Forecast Engine
output (same project, overlapping horizons), assumptions (discount rate,
average unit size, horizons).
Outputs: cumulative revenue and its NPV at each horizon year, plus total
revenue potential at full sell-out.
Dependencies: Pricing Forecast Engine, Sales Velocity Forecast Engine --
this engine never reads DataPoints directly, only composes their output.

Model, and its simplifications (documented, not silently assumed): neither
adapter currently supplies actual saleable area per unit, so
`average_unit_size_sqft` is a configurable assumption (standard
underwriting practice when exact unit-mix data isn't available yet) used
to convert PSF pricing into a per-unit price. `cumulative_revenue(Y)`
treats all units sold by year Y as transacting at year Y's nominal price
-- a lump-sum-at-checkpoint approximation, not a month-by-month cash flow
model.

Validation: pricing and sales velocity outputs must cover every requested
horizon year.
Failure modes: a requested horizon year missing from either input ->
InsufficientDataError.
"""


def calculate(*, pricing_output: dict, sales_velocity_output: dict, assumptions: dict) -> dict:
    discount_rate = assumptions["discount_rate_pct"] / 100
    avg_unit_size_sqft = assumptions["average_unit_size_sqft"]
    horizons = assumptions["horizons_years"]

    nominal_price_by_year = {h["year"]: h["nominal_price_per_sqft"] for h in pricing_output["horizons"]}
    units_sold_by_year = {h["year"]: h["units_sold_cumulative"] for h in sales_velocity_output["horizons"]}

    missing = [y for y in horizons if y not in nominal_price_by_year or y not in units_sold_by_year]
    if missing:
        raise InsufficientDataError(
            f"pricing/sales velocity outputs don't cover requested horizon year(s): {missing}"
        )

    unit_count = sales_velocity_output["unit_count"]
    terminal_year = max(horizons)
    total_revenue_potential = unit_count * nominal_price_by_year[terminal_year] * avg_unit_size_sqft

    horizon_forecasts = []
    for year in horizons:
        avg_unit_price = nominal_price_by_year[year] * avg_unit_size_sqft
        cumulative_revenue = units_sold_by_year[year] * avg_unit_price
        discounted_revenue = cumulative_revenue / ((1 + discount_rate) ** year)
        horizon_forecasts.append(
            {
                "year": year,
                "cumulative_revenue": round(cumulative_revenue, 2),
                "discounted_cumulative_revenue": round(discounted_revenue, 2),
            }
        )

    return {
        "engine_version": ENGINE_VERSION,
        "average_unit_size_sqft": avg_unit_size_sqft,
        "discount_rate_pct": assumptions["discount_rate_pct"],
        "total_revenue_potential_at_sellout": round(total_revenue_potential, 2),
        "horizons": horizon_forecasts,
    }
