from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://nova:nova_dev@localhost:5432/nova_hiring"
    REDIS_URL: str = "redis://localhost:6379"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    API_KEY_ADMIN: str = ""
    API_KEY_CANDIDATES: str = ""

    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    SESSION_TTL_SECONDS: int = 604800  # 7 days
    PROCESSING_LOCK_TTL: int = 30
    MAX_SESSION_MESSAGES: int = 50


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
