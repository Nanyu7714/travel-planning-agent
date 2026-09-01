from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "行旅"
    database_url: str = "sqlite:///../travel.db"
    app_base_url: str = "http://localhost:5173"
    jwt_secret: str = "dev-jwt-secret-change-me"
    csrf_secret: str = "dev-csrf-secret-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    inline_worker: bool = True
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 500
    amap_web_service_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
