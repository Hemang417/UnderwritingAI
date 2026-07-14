ENGINE_VERSION = "1.0.0"

"""Risk Engine (PRD 12.5).

Inputs: project_status (CanonicalProject.status), current pricing
DataPoint's staleness/confidence (if any), assumptions (per-category
weights, default score for categories with no differentiated signal yet,
a status->risk-score map, staleness/low-confidence pricing penalties).
Outputs: a 0-100 score per risk category (Construction, Developer,
Market, Demand, Execution, Pricing, Regulatory) plus a weighted composite,
with a human-readable explanation per category (PRD "explain every
score").
Dependencies: none directly, but the pricing category re-uses M3's
staleness/confidence machinery on whatever the current pricing DataPoint
is.
Model, honestly scoped: only Construction/Execution (from project status)
and Pricing (from data freshness/confidence) currently have real
differentiated signal. Developer, Market, Demand, and Regulatory have no
data source feeding them yet (no developer track-record DB, no market
data adapter) -- they get the configured neutral default, explicitly
labeled as such rather than a fabricated confident-looking number.
Validation: none -- every category has a documented fallback, so this
engine cannot fail from missing data.
Failure modes: none (always produces a result; the caller still catches
unexpected exceptions as ForecastRunStatus.FAILED).
"""


def calculate(*, project_status: str, pricing_signal: dict | None, assumptions: dict) -> dict:
    weights = assumptions["category_weights"]
    default_score = assumptions["default_score_no_data"]
    status_scores = assumptions["status_risk_scores"]

    construction_score = status_scores.get(project_status, default_score)
    execution_score = status_scores.get(project_status, default_score)

    if pricing_signal is None:
        pricing_score = default_score
        pricing_basis = "no pricing data available yet"
    else:
        pricing_score = 10.0
        basis_parts = ["fresh, confident pricing data"]
        if pricing_signal.get("is_stale"):
            pricing_score += assumptions["stale_pricing_penalty"]
            basis_parts = ["pricing data is stale"]
        confidence = pricing_signal.get("composite_confidence", 100.0)
        if confidence < assumptions["low_confidence_pricing_threshold"]:
            pricing_score += assumptions["low_confidence_pricing_penalty"]
            basis_parts.append("pricing data has low confidence")
        pricing_score = min(pricing_score, 100.0)
        pricing_basis = "; ".join(basis_parts)

    category_scores = {
        "construction": construction_score,
        "developer": default_score,
        "market": default_score,
        "demand": default_score,
        "execution": execution_score,
        "pricing": pricing_score,
        "regulatory": default_score,
    }

    category_explanations = {
        "construction": f"Derived from project status '{project_status}'.",
        "developer": "No developer track-record data source yet -- neutral configured default.",
        "market": "No market data adapter yet -- neutral configured default.",
        "demand": "No market data adapter yet -- neutral configured default.",
        "execution": f"Proxy from project status '{project_status}' pending a dedicated execution signal.",
        "pricing": f"Based on current pricing data: {pricing_basis}.",
        "regulatory": (
            "Baseline for a RERA-registered project; deeper compliance-history signal is future work."
        ),
    }

    composite = sum(category_scores[category] * weight for category, weight in weights.items())

    return {
        "engine_version": ENGINE_VERSION,
        "category_scores": category_scores,
        "category_explanations": category_explanations,
        "composite_risk_score": round(composite, 2),
    }
