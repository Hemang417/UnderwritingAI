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


@lru_cache
def get_settings() -> Settings:
    return Settings()
