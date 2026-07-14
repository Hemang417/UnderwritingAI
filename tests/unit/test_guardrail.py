from app.llm.guardrail import build_reference_set, extract_numeric_claims, validate

GENERATED_JSON = {
    "project": {"project_name": "Lodha Park"},
    "data_points": {
        "unit_count": {
            "value": 450,
            "source": "MahaRERA",
            "discrepancy": {
                "resolved_value": 450,
                "resolved_source": "MahaRERA",
                "rejected_value": 460,
                "rejected_source": "Developer Website",
                "rule_applied": "source_priority:['rera', 'developer_site']",
            },
        },
        "possession_date": {"value": "2027-12-31", "source": "MahaRERA"},
        "current_price_per_sqft": {"value": 18500.0, "source": "Developer Website"},
    },
    "forecasts": {
        "pricing": {
            "effective_annual_appreciation_rate_pct": 8.0,
            "horizons": [{"year": 1, "nominal_price_per_sqft": 19980.0}],
        },
        "financial": {"total_revenue_potential_at_sellout": 130000000.0},
    },
}


def test_extracts_plain_currency_number():
    claims = extract_numeric_claims("The price is ₹18,500 per sqft.")
    assert any(c.value == 18500.0 for c in claims)


def test_extracts_percentage_as_bare_number_not_double_counted():
    claims = extract_numeric_claims("Growth is expected at 8.0% annually.")
    values = [c.value for c in claims]
    assert values == [8.0]  # not also counted as a separate bare "8.0"


def test_extracts_lakh_and_crore_as_absolute_values():
    claims = extract_numeric_claims("Revenue potential of 1.3 crore, with a smaller parcel at 18.5 lakh.")
    values = sorted(c.value for c in claims)
    assert values == [1_850_000.0, 13_000_000.0]


def test_extracts_iso_and_dmy_dates_as_equivalent():
    claims = extract_numeric_claims("Possession is due 2027-12-31, also written 31-12-2027.")
    dates = [c.normalized_date for c in claims if c.kind == "date"]
    assert dates == ["2027-12-31", "2027-12-31"]


def test_reference_set_includes_discrepancy_rejected_value():
    ref = build_reference_set(GENERATED_JSON)
    values = {v for _, v in ref.numbers}
    assert 450.0 in values
    assert 460.0 in values  # ADR-016: the disclosed rejected value must be traceable too


def test_disclosed_rejected_value_is_not_wrongly_blocked():
    text = (
        "Unit count per MahaRERA: 450; per developer marketing materials: 460 -- RERA figure used "
        "per source-priority policy."
    )
    ref = build_reference_set(GENERATED_JSON)
    result = validate(text, ref)
    assert result.passed
    assert not result.unmatched


def test_fabricated_number_is_caught_as_unmatched():
    text = "An additional unverified projection of 987654.0 was noted."
    ref = build_reference_set(GENERATED_JSON)
    result = validate(text, ref)
    assert not result.passed
    assert len(result.unmatched) == 1
    assert "987654.0" in result.unmatched[0]["raw_text"]


def test_rounding_tolerance_allows_minor_formatting_differences():
    # LLM writes "19,980" for a JSON value stored as 19980.0 -- same number,
    # just comma-formatted; must match, not be flagged as unverifiable.
    text = "The projected price is ₹19,980 next year."
    ref = build_reference_set(GENERATED_JSON)
    result = validate(text, ref)
    assert result.passed


def test_rera_registration_number_is_not_treated_as_a_numeric_claim():
    # Discovered against a real Groq response: "RERA registration number is
    # P51900001234" must not extract "51900001234" as an unverifiable
    # numeric claim -- it's an identifier, not a fact the guardrail checks.
    text = "The RERA registration number for this project is P51900001234, per MahaRERA."
    ref = build_reference_set(GENERATED_JSON)
    result = validate(text, ref)
    assert result.passed
    assert not result.unmatched


def test_boolean_leaves_are_never_treated_as_numbers():
    # bool is an int subclass in Python -- must be excluded explicitly, or
    # a stray `"legal_review_signed_off": true` would silently become a
    # phantom reference number "1.0" the guardrail would wrongly accept.
    ref = build_reference_set({"flag": True, "count": 3})
    assert ref.numbers == [("/count", 3.0)]
