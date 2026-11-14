"""Application configuration loaded from environment / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "EvalForge AI"
    app_version: str = "1.0.0"
    environment: str = "development"  # development | production | test

    database_url: str = "sqlite:///./evalforge.db"

    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    max_upload_mb: int = 25
    max_records_per_dataset: int = 20000

    # Default evaluation / borderline thresholds (rubric overrides allowed)
    default_borderline_confidence_below: float = 0.6
    default_borderline_score_margin: float = 0.08

    # Engine identifier recorded on every finding (traceability)
    evaluator_version: str = "evalforge-engine 1.0.0"

    demo_marker: str = "[DEMONSTRATION DATA]"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
