from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ProcessingStage(StrEnum):
    PIPELINE = "pipeline"
    CLAIM = "claim"
    SETUP = "setup"
    PREPROCESSING = "preprocessing"
    PERSIST_PREPROCESSING = "persist_preprocessing"
    OCR = "ocr"
    PERSIST_OCR = "persist_ocr"
    PARSING = "parsing"
    SAVING = "saving"


class MetricOutcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    SKIPPED = "skipped"
    STOPPED = "stopped"


class ProcessingObservation(BaseModel):
    outcome: MetricOutcome = MetricOutcome.SUCCESS


class StageMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    attempts: int
    success: int
    error: int
    interrupted: int
    skipped: int
    stopped: int
    error_rate: float | None
    duration_samples: int
    mean_seconds: float | None
    mean_success_seconds: float | None
    mean_error_seconds: float | None


class ProcessingMetricsResponse(BaseModel):
    day: date
    timezone: str = "UTC"
    retention_days: int
    semantics: str = (
        "Completed attempts, not unique receipts; retries counted separately. "
        "error_rate=(error+interrupted)/(success+error+interrupted); "
        "skipped/stopped excluded. Durations exclude queue waiting; "
        "hard interruptions have unknown duration. Metrics are best-effort."
    )
    stages: dict[ProcessingStage, StageMetrics]
