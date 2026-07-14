import json

from groq import AsyncGroq

from app.llm.base import LLMResponse, PromptSpec


class GroqProvider:
    """Real Report Language Adapter backed by Groq's chat completions API.
    Only the already-computed, validated `json_slice` is ever sent -- no
    raw scraped documents, no PII beyond what's already in the structured
    facts (ADR-012). Low temperature by default (PromptSpec.temperature):
    this is presentation of fixed facts, not creative writing.
    """

    provider_name = "groq"

    def __init__(self, *, api_key: str, model: str):
        self._client = AsyncGroq(api_key=api_key)
        self._model = model

    async def generate(self, prompt: PromptSpec) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=prompt.temperature,
            messages=[
                {"role": "system", "content": prompt.system_instruction},
                {
                    "role": "user",
                    "content": (
                        "Here is the source data for this section, as JSON. Use only the values "
                        "present here -- never calculate, estimate, or invent a number:\n\n"
                        + json.dumps(prompt.json_slice, indent=2, default=str)
                    ),
                },
            ],
        )
        text = response.choices[0].message.content or ""
        return LLMResponse(text=text, provider_name=self.provider_name, model=self._model)
