import uuid

from app.discovery.models import CanonicalProject
from app.discovery.scoring import (
    CityScorer,
    CompositeRanker,
    ExactNameScorer,
    FuzzyNameScorer,
    HistoricalSelectionScorer,
    SearchInput,
    normalize_text,
)


def _project(**overrides) -> CanonicalProject:
    defaults = dict(
        id=uuid.uuid4(),
        developer_id=uuid.uuid4(),
        state="Maharashtra",
        rera_registration_number="P51900001234",
        project_name="Lodha Park",
        locality="Worli",
        city="Mumbai",
        status="under_construction",
    )
    defaults.update(overrides)
    return CanonicalProject(**defaults)


def test_normalize_text_collapses_case_and_whitespace():
    assert normalize_text("  Lodha   PARK  ") == "lodha park"


def test_exact_name_scorer():
    project = _project(project_name="Lodha Park")
    query = SearchInput(normalized_text="lodha park")
    assert ExactNameScorer().score(project, query, {}) == 100.0

    query_mismatch = SearchInput(normalized_text="godrej park avenue")
    assert ExactNameScorer().score(project, query_mismatch, {}) == 0.0


def test_fuzzy_name_scorer_is_deterministic_and_ranks_similarity():
    project = _project(project_name="Green Valley Heights")
    close = SearchInput(normalized_text="green valley height")
    far = SearchInput(normalized_text="totally different name")

    scorer = FuzzyNameScorer()
    close_score = scorer.score(project, close, {})
    far_score = scorer.score(project, far, {})

    assert close_score > far_score
    # same inputs -> same output, every time
    assert scorer.score(project, close, {}) == close_score


def test_city_scorer_not_applicable_without_city_hint():
    project = _project(city="Mumbai")
    query = SearchInput(normalized_text="lodha park", city_hint=None)
    assert CityScorer().score(project, query, {}) is None


def test_city_scorer_matches_case_insensitively():
    project = _project(city="Mumbai")
    match = SearchInput(normalized_text="lodha park", city_hint="mumbai")
    mismatch = SearchInput(normalized_text="lodha park", city_hint="Pune")

    assert CityScorer().score(project, match, {}) == 100.0
    assert CityScorer().score(project, mismatch, {}) == 0.0


def test_historical_selection_scorer_scales_and_caps():
    project = _project()
    query = SearchInput(normalized_text="lodha park")
    scorer = HistoricalSelectionScorer()

    assert scorer.score(project, query, {}) == 0.0
    assert scorer.score(project, query, {project.id: 1}) == 25.0
    assert scorer.score(project, query, {project.id: 10}) == 100.0  # capped, not 250


def test_composite_ranker_orders_by_score_and_renormalizes_when_city_not_given():
    exact_match = _project(project_name="Lodha Park", city="Mumbai")
    fuzzy_only = _project(project_name="Lodha Parc", city="Pune")

    weights = {"exact_name": 40, "fuzzy_name": 25, "city": 20, "historical_selection": 15}
    ranker = CompositeRanker(weights=weights)

    # No city hint: the "city" weight must drop out of the denominator
    # entirely rather than counting as a zero score for every candidate.
    query = SearchInput(normalized_text="lodha park", city_hint=None)
    results = ranker.rank([fuzzy_only, exact_match], query, historical_hits={})

    assert results[0].project is exact_match
    assert results[0].scores["city"] is None
    expected_weight_sum = weights["exact_name"] + weights["fuzzy_name"] + weights["historical_selection"]
    expected_numerator = weights["exact_name"] * 100 + weights["fuzzy_name"] * 100
    expected_composite = round(expected_numerator / expected_weight_sum, 2)
    assert results[0].composite_score == expected_composite


def test_composite_ranker_is_deterministic():
    projects = [_project(project_name="Lodha Park"), _project(project_name="Godrej Park Avenue")]
    weights = {"exact_name": 40, "fuzzy_name": 25, "city": 20, "historical_selection": 15}
    query = SearchInput(normalized_text="lodha park", city_hint="Mumbai")

    ranker = CompositeRanker(weights=weights)
    first_run = [r.composite_score for r in ranker.rank(projects, query, {})]
    second_run = [r.composite_score for r in ranker.rank(projects, query, {})]

    assert first_run == second_run
