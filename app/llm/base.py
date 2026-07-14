from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PromptSpec:
    """Everything one section's generation needs, and nothing more
    (least-privilege prompting, SAD S12): `json_slice` is scoped to this
    section only, never the full Report JSON. `template_version` is
    recorded on the resulting ReportSection so a past section's exact
    wording is reproducible against the prompt that produced it.
    """

    section_name: str
    system_instruction: str
    json_slice: dict
    template_version: str
    temperature: float = 0.1


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider_name: str
    model: str


class LLMProvider(Protocol):
    """Report Language Adapter interface (ADR-008). GroqProvider/
    GeminiProvider implement this now; a ClaudeProvider is a pure addition
    later with zero caller changes -- provider selection is
    configuration-driven, never hardcoded into the reporting service.
    """

    provider_name: str

    async def generate(self, prompt: PromptSpec) -> LLMResponse: ...
