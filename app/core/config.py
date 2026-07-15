from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"

    database_url: str = "postgresql+asyncpg://ic_platform:ic_platform@localhost:5432/ic_platform"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-every-environment"
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 30
    jwt_refresh_token_days: int = 14

    document_storage_dir: str = "./data/documents"
    tesseract_cmd: str | None = None  # override for the tesseract binary path (e.g. on Windows dev)

    # Report Language Adapter (M7) -- only structured JSON is ever sent to
    # this provider, never raw documents/PII (ADR-012).
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    # Live MahaRERA adapter (separate from the fixture-backed one -- see
    # app/adapters/maha_rera.py). The session token is MahaRERA's OWN bearer
    # token, not this platform's; it comes from a human manually solving a
    # CAPTCHA via `python scripts/setup_maharera_session.py` -- there is no
    # automated way to obtain or refresh it, and none should be built. Lasts
    # ~100 minutes. Read fresh from this file on every request (see
    # app/adapters/maha_rera_session.py) rather than cached in Settings, so
    # re-running the setup script takes effect without an API restart.
    maharera_token_file_path: str = "./config/maharera_token.json"
    maharera_request_timeout_seconds: float = 15.0
    maharera_rate_limit_delay_seconds: float = 0.5
    maharera_max_retries: int = 3
    maharera_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
