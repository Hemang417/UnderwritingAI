from typing import Protocol


class DimensionAdjuster(Protocol):
    """One assumption dimension's transform under a scenario (PRD 12.4:
    inflation, interest rates, demand, supply, construction delays,
    developer execution, pricing growth, sales velocity). Each adjuster is
    pure and independent -- the Scenario Engine composes them, it never
    encodes dimension-specific math itself.
    """

    name: str

    def adjust(self, base: dict, scenario_adjustments: dict) -> dict:
        """Return a new dict with this dimension's scenario delta applied
        on top of `base` (either a base engine's assumption parameters, or
        -- for risk -- its base category_scores). Unrecognized or absent
        keys in `scenario_adjustments` are no-ops, so a scenario only needs
        to specify the dimensions it actually wants to move.
        """
        ...


class PricingParameterAdjuster:
    name = "pricing"

    def adjust(self, base: dict, scenario_adjustments: dict) -> dict:
        adjusted = dict(base)
        pricing_growth_delta = scenario_adjustments.get("pricing_growth_delta_pct", 0.0)
        adjusted["annual_appreciation_rate_pct"] = base["annual_appreciation_rate_pct"] + pricing_growth_delta
        adjusted["annual_inflation_rate_pct"] = base["annual_inflation_rate_pct"] + scenario_adjustments.get(
            "inflation_delta_pct", 0.0
        )
        return adjusted


class SalesVelocityParameterAdjuster:
    name = "sales_velocity"

    def adjust(self, base: dict, scenario_adjustments: dict) -> dict:
        adjusted = dict(base)
        multiplier = scenario_adjustments.get("sales_velocity_multiplier", 1.0)
        adjusted["monthly_absorption_rate_pct"] = base["monthly_absorption_rate_pct"] * multiplier
        return adjusted


class FinancialParameterAdjuster:
    name = "financial"

    def adjust(self, base: dict, scenario_adjustments: dict) -> dict:
        adjusted = dict(base)
        adjusted["discount_rate_pct"] = base["discount_rate_pct"] + scenario_adjustments.get(
            "interest_rate_delta_pct", 0.0
        )
        return adjusted


class RiskCategoryAdjuster:
    """Operates on the base Risk engine's category_scores directly, not on
    its input assumptions: risk categories are status/data-driven, not
    rate-driven, so a scenario represents a hypothetical shift in
    conditions rather than a different reading of the same DataPoints.
    Construction delays and developer-execution slippage are the same
    underlying dimension for both the 'construction'/'execution' and
    'developer' categories respectively, per PRD 12.4's dimension list.
    """

    name = "risk"
    _CATEGORY_ADJUSTMENT_KEYS = {
        "construction": "construction_delay_risk_pts",
        "execution": "construction_delay_risk_pts",
        "developer": "developer_execution_risk_pts",
        "demand": "demand_risk_pts",
        "market": "supply_risk_pts",
    }

    def adjust(self, base: dict, scenario_adjustments: dict) -> dict:
        adjusted = dict(base)
        for category, key in self._CATEGORY_ADJUSTMENT_KEYS.items():
            if category in adjusted and key in scenario_adjustments:
                adjusted[category] = max(0.0, min(100.0, adjusted[category] + scenario_adjustments[key]))
        return adjusted
