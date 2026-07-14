from fastapi import HTTPException, status

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.groq_provider import GroqProvider


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency, overridable exactly like get_session -- tests
    override this with FixtureLLMProvider so the automated suite never
    makes a live call (SAD S17's adapter-contract-test philosophy, applied
    to the Report Language Adapter). Provider selection is
    configuration-driven (ADR-008): swapping in GeminiProvider or a real
    ClaudeProvider later is a change here only, not in any caller.
    """
    settings = get_settings()
    if not settings.groq_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No LLM provider configured -- set GROQ_API_KEY.",
        )
    return GroqProvider(api_key=settings.groq_api_key, model=settings.groq_model)
