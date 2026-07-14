from app.llm.base import LLMResponse, PromptSpec

# A value no real DataPoint/ForecastRun/ScenarioResult in this system would
# ever produce -- deliberately unmatchable against any reference set, used
# to simulate a hallucinated figure for guardrail negative tests.
_FABRICATED_NUMBER = "987654.0"


def _flatten_numeric_paths(obj, path: str = "") -> list[tuple[str, object]]:
    """Collects (json_pointer_path, value) pairs for every number/date-like
    string leaf, so the fixture provider can cite real values by path
    without knowing this particular slice's shape in advance."""
    found: list[tuple[str, object]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.extend(_flatten_numeric_paths(value, f"{path}/{key}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(_flatten_numeric_paths(value, f"{path}/{index}"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        found.append((path, obj))
    elif isinstance(obj, str) and len(obj) == 10 and obj.count("-") == 2:
        found.append((path, obj))  # ISO date string, e.g. "2027-12-31"
    return found


class FixtureLLMProvider:
    """Deterministic, offline stand-in for a real LLMProvider -- mirrors
    app.adapters.fixture_client.FixtureClient's role for data adapters:
    proves the calling code's contract (guardrail, bounded regeneration,
    report assembly) without a live API call, cost, or network dependency
    in the automated test suite. `corrupt_sections` deliberately injects an
    unmatchable number into the named sections' output, simulating a
    hallucination for the guardrail's mandated negative-test coverage.
    """

    provider_name = "fixture"

    def __init__(self, *, corrupt_sections: set[str] | None = None):
        self._corrupt_sections = corrupt_sections or set()
        self.call_count = 0

    async def generate(self, prompt: PromptSpec) -> LLMResponse:
        self.call_count += 1
        pairs = _flatten_numeric_paths(prompt.json_slice)[:6]
        citations = "; ".join(f"{path.strip('/').replace('/', '.')} is {value}" for path, value in pairs)
        text = (
            f"[Fixture-generated {prompt.section_name} section, template v{prompt.template_version}.] "
            f"Supporting figures from the provided data: {citations or 'no numeric data available'}."
        )
        if prompt.section_name in self._corrupt_sections:
            text += f" An additional unverified projection of {_FABRICATED_NUMBER} was also noted."
        return LLMResponse(text=text, provider_name=self.provider_name, model="fixture-v1")
