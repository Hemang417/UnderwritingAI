from app.reporting.assembly import SECTION_JSON_SLICERS, SECTION_NAMES

SAMPLE_DATA = {
    "project": {
        "project_name": "Lodha Park",
        "developer": "Lodha Group",
        "city": "Mumbai",
        "locality": "Worli",
    },
    "data_points": {
        "unit_count": {"value": 450.0, "source": "MahaRERA"},
        "current_price_per_sqft": {"value": 18500.0, "source": "Developer Website"},
        "possession_date": {"value": "2027-12-31", "source": "MahaRERA"},
    },
    "forecasts": {
        "pricing": {"effective_annual_appreciation_rate_pct": 8.0},
        "sales_velocity": {"sell_through_timeline_months": 42.0},
        "financial": {"total_revenue_potential_at_sellout": 130000000.0},
        "risk": {
            "category_scores": {"construction": 70.0, "developer": 50.0, "market": 50.0, "demand": 50.0},
            "category_explanations": {"developer": "No data source yet -- neutral configured default."},
            "composite_risk_score": 45.0,
        },
    },
    "scenarios": {
        "bear": {"pricing": {"effective_annual_appreciation_rate_pct": 4.0}},
        "base": {"pricing": {"effective_annual_appreciation_rate_pct": 8.0}},
        "bull": {"pricing": {"effective_annual_appreciation_rate_pct": 11.0}},
    },
}


def test_eleven_sections_are_defined():
    assert len(SECTION_NAMES) == 11


def test_every_slicer_returns_a_dict_without_raising():
    for section_name in SECTION_NAMES:
        result = SECTION_JSON_SLICERS[section_name](SAMPLE_DATA)
        assert isinstance(result, dict)
        assert result  # never an empty, useless slice


def test_executive_summary_gets_the_full_data():
    result = SECTION_JSON_SLICERS["executive_summary"](SAMPLE_DATA)
    assert result == SAMPLE_DATA


def test_pricing_analysis_is_scoped_and_excludes_unrelated_data():
    result = SECTION_JSON_SLICERS["pricing_analysis"](SAMPLE_DATA)
    assert "pricing_forecast" in result
    assert "current_price_per_sqft" in result
    assert "scenarios" not in result
    assert "unit_count" not in result


def test_key_assumptions_gets_data_points_where_discrepancies_live():
    result = SECTION_JSON_SLICERS["key_assumptions"](SAMPLE_DATA)
    assert result == {"data_points": SAMPLE_DATA["data_points"]}


def test_developer_analysis_honestly_scoped_to_developer_signal_only():
    result = SECTION_JSON_SLICERS["developer_analysis"](SAMPLE_DATA)
    assert result["risk_developer_explanation"] == "No data source yet -- neutral configured default."
    assert "pricing_forecast" not in result
