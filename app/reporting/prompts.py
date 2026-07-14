"""Per-section system instructions (SAD S12: a versioned config asset, not
scattered inline strings -- `TEMPLATE_VERSION` is recorded on every
ReportSection so a past section's exact wording is reproducible against the
prompt that produced it). Every instruction repeats the same hard
constraint deliberately, rather than relying on a single shared preamble,
because each section is sent to the LLM independently (least-privilege
prompting) with no other context carried over.
"""

TEMPLATE_VERSION = "1.0.0"

_COMMON_RULES = (
    "You are drafting one section of an institutional real estate investment committee report. "
    "You will be given a JSON object with the only facts you may reference. Rules, no exceptions: "
    "(1) Use only numbers, dates, and facts that appear in the JSON below -- never calculate, "
    "estimate, round differently, or invent any figure, including simple arithmetic. "
    "(2) If a field includes a 'discrepancy' block, you must explicitly state both the resolved "
    "value and the rejected value with their sources and the rule applied -- do not present only "
    "the resolved figure as if no disagreement existed. "
    "(3) Write in a neutral, professional tone suitable for an investment committee. "
    "(4) Output plain prose paragraphs only, no headings, no bullet lists, no markdown."
)

SECTION_SYSTEM_INSTRUCTIONS: dict[str, str] = {
    "executive_summary": (
        _COMMON_RULES
        + " Write the Executive Summary: a concise synthesis of the project, its pricing and sales "
        "velocity outlook, the scenario range (Bear/Base/Bull), and overall risk -- 3-5 sentences."
    ),
    "project_overview": (
        _COMMON_RULES
        + " Write the Project Overview: identify the project, its developer, location, RERA "
        "registration, and current status, plus the current unit count and price per sqft."
    ),
    "developer_analysis": (
        _COMMON_RULES
        + " Write the Developer Analysis. If the developer risk category score has no differentiated "
        "signal yet, state that plainly rather than fabricating a track record -- do not imply "
        "confidence the data doesn't support."
    ),
    "market_analysis": (
        _COMMON_RULES
        + " Write the Market Analysis covering the project's city and locality, and the market/demand "
        "risk category scores. If those scores have no differentiated signal yet (no market data "
        "source configured), state that honestly."
    ),
    "pricing_analysis": (
        _COMMON_RULES
        + " Write the Pricing Analysis: current price per sqft, the effective annual appreciation "
        "rate assumed, and the nominal/real price forecasts at each horizon year provided."
    ),
    "sales_velocity_analysis": (
        _COMMON_RULES
        + " Write the Sales Velocity Analysis: current unit count, the monthly absorption rate "
        "assumed, the sell-through timeline, and cumulative units sold/inventory remaining at each "
        "horizon year provided."
    ),
    "scenario_analysis": (
        _COMMON_RULES
        + " Write the Scenario Analysis comparing the Bear, Base, and Bull scenario outputs provided "
        "-- pricing, sales velocity, financial, and risk implications of each."
    ),
    "risk_assessment": (
        _COMMON_RULES
        + " Write the Risk Assessment: the composite risk score and each category score with its "
        "explanation, exactly as provided. Do not soften or omit a category explanation that says a "
        "score is a neutral default with no data source yet."
    ),
    "key_assumptions": (
        _COMMON_RULES
        + " Write the Key Assumptions section. This section exists specifically to disclose data "
        "provenance and disagreements: for every field with a 'discrepancy' block, state both the "
        "resolved and rejected values, their sources, and the rule applied (e.g. 'Unit count per "
        "MahaRERA: 450; per developer marketing materials: 460 -- RERA figure used per source-"
        "priority policy'). Also state that all forecasts are deterministic given fixed inputs and "
        "configuration -- this is a reproducibility property, not a predictive-accuracy guarantee."
    ),
    "investment_recommendation": (
        _COMMON_RULES
        + " Write the Investment Recommendation synthesizing the financial forecast, risk profile, "
        "and scenario range provided. Do not state a number that isn't present in the JSON, and do "
        "not imply certainty beyond what the Bear/Base/Bull range shows."
    ),
    "conclusion": (
        _COMMON_RULES
        + " Write a brief Conclusion (2-3 sentences) referencing the financial forecast figures "
        "provided."
    ),
}
