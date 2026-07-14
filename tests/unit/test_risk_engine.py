from app.analytics.engines import risk

ASSUMPTIONS = {
    "category_weights": {
        "construction": 0.20,
        "developer": 0.15,
        "market": 0.15,
        "demand": 0.15,
        "execution": 0.10,
        "pricing": 0.15,
        "regulatory": 0.10,
    },
    "default_score_no_data": 50.0,
    "status_risk_scores": {"under_construction": 70.0, "nearing_completion": 40.0, "completed": 10.0},
    "stale_pricing_penalty": 20.0,
    "low_confidence_pricing_threshold": 70.0,
    "low_confidence_pricing_penalty": 15.0,
}


def test_composite_is_weighted_average_of_category_scores():
    result = risk.calculate(
        project_status="under_construction",
        pricing_signal={"is_stale": False, "composite_confidence": 95.0},
        assumptions=ASSUMPTIONS,
    )
    expected = sum(
        result["category_scores"][cat] * weight for cat, weight in ASSUMPTIONS["category_weights"].items()
    )
    assert result["composite_risk_score"] == round(expected, 2)


def test_completed_project_has_lower_construction_risk_than_under_construction():
    under_construction = risk.calculate(
        project_status="under_construction", pricing_signal=None, assumptions=ASSUMPTIONS
    )
    completed = risk.calculate(project_status="completed", pricing_signal=None, assumptions=ASSUMPTIONS)
    completed_score = completed["category_scores"]["construction"]
    under_construction_score = under_construction["category_scores"]["construction"]
    assert completed_score < under_construction_score


def test_missing_pricing_signal_uses_neutral_default_not_a_crash():
    result = risk.calculate(project_status="under_construction", pricing_signal=None, assumptions=ASSUMPTIONS)
    assert result["category_scores"]["pricing"] == ASSUMPTIONS["default_score_no_data"]


def test_stale_pricing_increases_pricing_risk():
    fresh = risk.calculate(
        project_status="under_construction",
        pricing_signal={"is_stale": False, "composite_confidence": 95.0},
        assumptions=ASSUMPTIONS,
    )
    stale = risk.calculate(
        project_status="under_construction",
        pricing_signal={"is_stale": True, "composite_confidence": 95.0},
        assumptions=ASSUMPTIONS,
    )
    assert stale["category_scores"]["pricing"] > fresh["category_scores"]["pricing"]


def test_low_confidence_pricing_increases_pricing_risk():
    confident = risk.calculate(
        project_status="under_construction",
        pricing_signal={"is_stale": False, "composite_confidence": 95.0},
        assumptions=ASSUMPTIONS,
    )
    low_confidence = risk.calculate(
        project_status="under_construction",
        pricing_signal={"is_stale": False, "composite_confidence": 40.0},
        assumptions=ASSUMPTIONS,
    )
    assert low_confidence["category_scores"]["pricing"] > confident["category_scores"]["pricing"]


def test_every_category_has_an_explanation():
    result = risk.calculate(project_status="under_construction", pricing_signal=None, assumptions=ASSUMPTIONS)
    assert set(result["category_explanations"]) == set(result["category_scores"])


def test_calculation_is_deterministic():
    signal = {"is_stale": False, "composite_confidence": 95.0}
    kwargs = {"project_status": "under_construction", "pricing_signal": signal, "assumptions": ASSUMPTIONS}
    first = risk.calculate(**kwargs)
    second = risk.calculate(**kwargs)
    assert first == second
