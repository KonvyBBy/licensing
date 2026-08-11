from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- core ---
    APP_NAME: str = "LicenseServer"
    ENVIRONMENT: str = "development"  # development | production
    # Must be 32+ chars in production. Signs admin JWTs and is the pepper for
    # HWID hashing. NEVER expose to clients.
    SECRET_KEY: str = "CHANGE-ME-please-use-a-long-random-string"
    API_PREFIX: str = "/api/v1"

    # --- database ---
    # sqlite for local/dev; Postgres in production (survives restarts).
    DATABASE_URL: str = "sqlite+aiosqlite:///./license.db"

    # --- tokens ---
    ADMIN_ACCESS_MINUTES: int = 15
    ADMIN_REFRESH_DAYS: int = 30
    SESSION_HOURS: int = 24  # client device session lifetime

    # --- security policy ---
    PASSWORD_MIN_LENGTH: int = 10
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 15

    # --- client auth ---
    MAX_ACTIVATIONS_PER_LICENSE: int = 1
    # Minimum license length accepted from the SDK (the real check is server-side).
    LICENSE_FORMAT: str = "XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"

    # --- admin bootstrap ---
    # First-run admin account (email + password). Change after first login.
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "ChangeMe-1234567890!"

    # --- CORS / cookies ---
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://localhost:3000"
    COOKIE_SECURE: bool = False  # MUST be true in production (HTTPS)

    @property
    def allowed_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @field_validator("SECRET_KEY")
    @classmethod
    def _secret_key(cls, v: str) -> str:
        if v == "CHANGE-ME-please-use-a-long-random-string":
            return v
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
