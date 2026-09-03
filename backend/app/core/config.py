from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "行旅"
    database_url: str = "sqlite:///../travel.db"
    app_base_url: str = "http://localhost:5173"
    jwt_secret: str = "dev-jwt-secret-change-me"
    csrf_secret: str = "dev-csrf-secret-change-me"
    admin_initial_password: str | None = None
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    environment: str = "development"
    mail_delivery_mode: str = "console"
    mail_from: str = "noreply@travel.local"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    auth_email_token_minutes: int = 30
    email_verification_code_minutes: int = 3
    password_reset_token_minutes: int = 30
    inline_worker: bool = True
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 500
    amap_web_service_key: str | None = None
    # Optional free-stock photo providers. Leave empty to use Wikimedia Commons only.
    unsplash_access_key: str | None = None
    pexels_api_key: str | None = None
    # When true, fetched photos are downloaded into backend/media instead of only storing remote URLs.
    photo_download_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
