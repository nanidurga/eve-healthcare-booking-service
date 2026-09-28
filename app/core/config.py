"""Application settings, loaded from the environment (or a local .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Long enough for HS256; obviously not a secret. Production must override it.
DEV_JWT_SECRET = "insecure-development-secret-do-not-use-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Application
    env: Literal["development", "test", "production"] = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "sqlite+aiosqlite:///./eve.db"

    # Auth
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    # bcrypt cost factor. 12 is a sane production default; the test suite
    # drops it so hashing does not dominate the run time.
    bcrypt_rounds: int = 12

    # Payment simulation. Deterministic on purpose: random failures make tests
    # flaky and make a reviewer's manual run unreproducible.
    payment_failure_cents: int = 13

    # Optional shared secret for POST /payments/webhook. Left empty by default
    # so the endpoint is callable straight from the docs page; set it and the
    # endpoint starts requiring a matching X-Webhook-Secret header.
    webhook_secret: str = ""

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @model_validator(mode="after")
    def _reject_dev_secret_in_production(self) -> "Settings":
        if self.env == "production" and self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET must be set to a real secret when ENV=production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
