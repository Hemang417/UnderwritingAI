import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Protocol

from app.discovery.models import CanonicalProject

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Lowercase, trim, and collapse whitespace.

    Used both for matching candidate project names and for building the
    ConfirmedMapping lookup key, so two searches that only differ in casing
    or extra spaces hit the same mapping.
    """
    return _WHITESPACE_RE.sub(" ", value.strip().lower())


@dataclass(frozen=True)
class SearchInput:
    normalized_text: str
    city_hint: str | None = None


class Scorer(Protocol):
    name: str

    def score(
        self, candidate: CanonicalProject, query: SearchInput, historical_hits: dict[uuid.UUID, int]
    ) -> float | None:
        """Return a 0-100 score, or None if this scorer doesn't apply to this query."""
        ...


class ExactNameScorer:
    name = "exact_name"

    def score(self, candidate, query, historical_hits):
        return 100.0 if normalize_text(candidate.project_name) == query.normalized_text else 0.0


class FuzzyNameScorer:
    name = "fuzzy_name"

    def score(self, candidate, query, historical_hits):
        ratio = SequenceMatcher(None, normalize_text(candidate.project_name), query.normalized_text).ratio()
        return round(ratio * 100, 2)


class CityScorer:
    """Only applies when the analyst supplied a city hint -- otherwise this
    dimension has nothing to compare against and is excluded from the
    composite rather than penalizing every candidate equally."""

    name = "city"

    def score(self, candidate, query, historical_hits):
        if not query.city_hint:
            return None
        return 100.0 if normalize_text(candidate.city) == normalize_text(query.city_hint) else 0.0


class HistoricalSelectionScorer:
    """Boosts projects analysts have previously confirmed for *any* search
    string, on the theory that a frequently-selected project is more likely
    to be the intended one again. Always applicable (0 if no history)."""

    name = "historical_selection"
    _POINTS_PER_HIT = 25.0

    def score(self, candidate, query, historical_hits):
        hits = historical_hits.get(candidate.id, 0)
        return min(100.0, hits * self._POINTS_PER_HIT)


DEFAULT_SCORERS: list[Scorer] = [
    ExactNameScorer(),
    FuzzyNameScorer(),
    CityScorer(),
    HistoricalSelectionScorer(),
]


@dataclass
class ScoredCandidate:
    project: CanonicalProject
    scores: dict[str, float | None]
    composite_score: float


@dataclass
class CompositeRanker:
    """Deterministic, config-driven weighted scoring (PRD "Candidate
    Ranking"): given the same candidates, query, weights, and historical
    hit counts, always produces the same ranking -- no hidden state.
    """

    weights: dict[str, float]
    scorers: list[Scorer] = field(default_factory=lambda: list(DEFAULT_SCORERS))

    def rank(
        self,
        candidates: list[CanonicalProject],
        query: SearchInput,
        historical_hits: dict[uuid.UUID, int],
    ) -> list[ScoredCandidate]:
        results = []
        for candidate in candidates:
            scores = {s.name: s.score(candidate, query, historical_hits) for s in self.scorers}
            applicable = {name: value for name, value in scores.items() if value is not None}
            weight_sum = sum(self.weights.get(name, 0) for name in applicable)
            composite = (
                sum(self.weights.get(name, 0) * value for name, value in applicable.items()) / weight_sum
                if weight_sum > 0
                else 0.0
            )
            results.append(
                ScoredCandidate(project=candidate, scores=scores, composite_score=round(composite, 2))
            )

        results.sort(key=lambda r: r.composite_score, reverse=True)
        return results
