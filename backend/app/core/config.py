import itertools
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class ImageSettings(BaseSettings):
    orientation_apply_model_rotation: bool = False
    orientation_min_confidence: float = Field(
        default=0.8, ge=0, le=1, allow_inf_nan=False
    )
    orientation_model_dir: Path = BACKEND_ROOT / "models" / "doc-orientation"
    orientation_device: str = "cpu"
    orientation_cpu_threads: int = Field(default=4, ge=1, le=64)
    url_ttl_seconds: int = Field(default=300, ge=1, le=900)
    max_upload_bytes: PositiveInt = 10 * 1024 * 1024
    max_pixels: PositiveInt = 20_000_000
    formats: dict[str, tuple[str, str]] = Field(
        default_factory=lambda: {
            "JPEG": ("jpg", "image/jpeg"),
            "PNG": ("png", "image/png"),
            "WEBP": ("webp", "image/webp"),
        }
    )

    model_config = SettingsConfigDict(
        env_prefix="IMAGE_",
        env_file=BACKEND_ROOT / ".env.backend",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class OcrSettings(BaseSettings):
    model_dir: Path = BACKEND_ROOT / "models" / "ocr"
    detection_model_name: str = "PP-OCRv5_mobile_det"
    recognition_model_name: str = "cyrillic_PP-OCRv5_mobile_rec"
    model_files: tuple[str, ...] = (
        "inference.json",
        "inference.pdiparams",
        "inference.yml",
    )
    device: str = "cpu"
    cpu_threads: int = Field(default=4, ge=1, le=64)

    model_config = SettingsConfigDict(
        env_prefix="OCR_",
        env_file=BACKEND_ROOT / ".env.backend",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class MetricsSettings(BaseSettings):
    access_token: SecretStr | None = None
    retention_days: int = Field(default=30, ge=1, le=365)
    redis_timeout_seconds: float = Field(default=0.2, gt=0, le=2, allow_inf_nan=False)

    model_config = SettingsConfigDict(
        env_prefix="METRICS_",
        env_file=BACKEND_ROOT / ".env.backend",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class AnalyticsSettings(BaseSettings):
    timezone: str = "Asia/Omsk"
    max_period_days: int = Field(default=366, ge=1, le=36600)

    model_config = SettingsConfigDict(
        env_prefix="ANALYTICS_",
        env_file=BACKEND_ROOT / ".env.backend",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("ANALYTICS_TIMEZONE must be an IANA timezone") from error
        return value


class LlmSettings(BaseSettings):
    provider: Literal["ollama"] = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model_name: str = Field(
        default="qwen3.5:4b",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    timeout_seconds: float = Field(default=90, gt=0, le=300, allow_inf_nan=False)
    connect_timeout_seconds: float = Field(default=3, gt=0, le=30, allow_inf_nan=False)
    retry_intervals_seconds: tuple[
        Annotated[float, Field(ge=0, le=30, allow_inf_nan=False)], ...
    ] = Field(default=(1, 3), max_length=2)
    temperature: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    seed: int = Field(default=42, ge=0, le=2147483647)
    num_ctx: int = Field(default=8192, ge=2048, le=32768)
    num_predict: int = Field(default=2048, ge=128, le=8192)
    think: bool | None = False
    keep_alive_seconds: int = Field(default=300, ge=0, le=3600)
    max_response_bytes: int = Field(default=1024 * 1024, ge=1024, le=4 * 1024 * 1024)

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=BACKEND_ROOT / ".env.backend",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    @field_validator("base_url")
    @classmethod
    def validate_local_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname
            not in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port == 0
        ):
            raise ValueError(
                "LLM_BASE_URL must point to local Ollama without credentials or a path"
            )
        return value.rstrip("/")

    @field_validator("model_name")
    @classmethod
    def reject_cloud_model(cls, value: str) -> str:
        if ":cloud" in value.lower():
            raise ValueError(
                "Cloud models are not supported by the local Ollama provider"
            )
        return value

    @field_validator("retry_intervals_seconds")
    @classmethod
    def validate_backoff(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(a > b for a, b in itertools.pairwise(value)):
            raise ValueError("LLM retry intervals must be non-decreasing")
        return value


class ParsingSettings(BaseSettings):
    timezone: str | None = None
    total_tolerance: Decimal = Field(
        default=Decimal("0.05"),
        ge=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
    )

    model_config = SettingsConfigDict(
        env_prefix="PARSING_",
        env_file=BACKEND_ROOT / ".env.backend",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("PARSING_TIMEZONE must be an IANA timezone") from error
        return value


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    session_ttl_seconds: PositiveInt = 604800
    minio_url: str
    minio_region: str
    minio_root_user: str
    minio_root_password: str
    minio_bucket: str
    minio_public_url: str = "http://127.0.0.1:9000"
    cookie_secure: bool = False
    login_rate_limit_attempts: PositiveInt = 5
    login_rate_limit_window_seconds: PositiveInt = 900
    receipt_retry_intervals_seconds: tuple[PositiveInt, ...] = Field(
        default=(10, 30, 90), max_length=5
    )

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

    @field_validator("receipt_retry_intervals_seconds")
    @classmethod
    def validate_receipt_retry_intervals(
        cls, value: tuple[int, ...]
    ) -> tuple[int, ...]:
        if any(current > following for current, following in itertools.pairwise(value)):
            raise ValueError("RECEIPT_RETRY_INTERVALS_SECONDS must be non-decreasing")

        if any(interval > 86400 for interval in value):
            raise ValueError("Receipt retry intervals must not exceed 86400 seconds")

        return value


setting = Settings()
image_settings = ImageSettings()
ocr_settings = OcrSettings()
metrics_settings = MetricsSettings()
parsing_settings = ParsingSettings()
analytics_settings = AnalyticsSettings()
llm_settings = LlmSettings()
