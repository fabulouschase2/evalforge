"""Application configuration loaded from environment / .env file."""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that must never be used as the signing key in production.
INSECURE_SECRET_KEY_DEFAULTS = {"", "change-me-in-production", "secret", "changeme"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "EvalForge AI"
    app_version: str = "1.0.0"
    environment: str = "development"  # development | test | production

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

    # Demo seeding: allowed in development/test by default; in production it
    # must be explicitly opted into with ENABLE_DEMO=true. Demo accounts use
    # published passwords and must never exist unintentionally in production.
    enable_demo: bool = True

    # Per-IP login attempts allowed per 5-minute window (brute-force baseline).
    login_rate_limit: int = 60

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Refuse insecure configuration when running in production."""
        if self.environment.strip().lower() == "production":
            if self.secret_key.strip().lower() in INSECURE_SECRET_KEY_DEFAULTS or len(self.secret_key) < 32:
                raise ValueError(
                    "REFUSING TO START: SECRET_KEY is missing, a known default, or shorter than "
                    "32 characters. Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
