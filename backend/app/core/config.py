from pathlib import Path
from pydantic import PositiveInt, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    session_ttl_seconds: PositiveInt = 604800
    minio_url: str
    minio_region: str
    minio_root_user: str
    minio_root_password: str
    minio_bucket: str
    cookie_secure: bool = False
    login_rate_limit_attempts: PositiveInt = 5
    login_rate_limit_window_seconds: PositiveInt = 900

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env.backend",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL должен использовать postgresql+psycopg://")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL должен использовать redis:// or rediss://")
        return value


setting = Settings()
