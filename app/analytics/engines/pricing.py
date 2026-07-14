from app.analytics.engines.base import InsufficientDataError

ENGINE_VERSION = "1.0.0"

"""Pricing Forecast Engine (PRD 12.1).

Inputs: current_price_per_sqft (DataPoint), assumptions (annual
appreciation/inflation/developer-premium/infrastructure-impact rates,
forecast horizons).
Outputs: nominal and real price per sqft at each horizon year.
Dependencies: none (base engine).
Model: compound annual growth. effective_rate = appreciation +
developer_premium + infrastructure_impact; nominal(y) = current * (1 +
effective_rate)^y; real(y) = nominal(y) / (1 + inflation_rate)^y.
Validation: current_price_per_sqft must be a positive number.
Failure modes: missing/non-positive price -> InsufficientDataError.
"""


def calculate(*, current_price_per_sqft: float, assumptions: dict) -> dict:
    if current_price_per_sqft is None or current_price_per_sqft <= 0:
        raise InsufficientDataError("current_price_per_sqft must be a positive number")

    appreciation_rate = assumptions["annual_appreciation_rate_pct"] / 100
    inflation_rate = assumptions["annual_inflation_rate_pct"] / 100
    developer_premium = assumptions.get("developer_premium_pct", 0.0) / 100
    infra_impact = assumptions.get("infrastructure_impact_pct", 0.0) / 100
    horizons = assumptions["horizons_years"]

    effective_rate = appreciation_rate + developer_premium + infra_impact

    horizon_forecasts = []
    for year in horizons:
        nominal_psf = current_price_per_sqft * ((1 + effective_rate) ** year)
        real_psf = nominal_psf / ((1 + inflation_rate) ** year)
        horizon_forecasts.append(
            {
                "year": year,
                "nominal_price_per_sqft": round(nominal_psf, 2),
                "real_price_per_sqft": round(real_psf, 2),
            }
        )

    return {
        "engine_version": ENGINE_VERSION,
        "current_price_per_sqft": current_price_per_sqft,
        "effective_annual_appreciation_rate_pct": round(effective_rate * 100, 4),
        "horizons": horizon_forecasts,
    }
