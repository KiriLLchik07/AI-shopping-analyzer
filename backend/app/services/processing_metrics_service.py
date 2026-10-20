import logging
import math
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from time import perf_counter

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from backend.app.core.config import metrics_settings, setting
from backend.app.repositories.processing_metrics_repository import (
    ProcessingMetricsRepository,
)
from backend.app.schemas.processing_metrics import (
    MetricOutcome,
    ProcessingMetricsResponse,
    ProcessingObservation,
    ProcessingStage,
    StageMetrics,
)

logger = logging.getLogger(__name__)


class ProcessingMetricsService:
    def __init__(self, repository: ProcessingMetricsRepository) -> None:
        self.repository = repository

    def record(
        self,
        stage: ProcessingStage,
        outcome: MetricOutcome,
        elapsed_seconds: float | None = None,
    ) -> None:
        logger.info(
            "Processing metric stage=%s outcome=%s elapsed_seconds=%s",
            stage.value,
            outcome.value,
            elapsed_seconds,
        )
        try:
            if elapsed_seconds is not None and (
                not math.isfinite(elapsed_seconds) or elapsed_seconds < 0
            ):
                raise ValueError("Invalid processing duration")
            self.repository.record(
                datetime.now(UTC).date(), stage, outcome, elapsed_seconds
            )
        except Exception:
            logger.warning(
                "Could not persist processing metric stage=%s outcome=%s",
                stage.value,
                outcome.value,
                exc_info=True,
            )

    @contextmanager
    def measure(
        self, stage: ProcessingStage
    ) -> Generator[ProcessingObservation, None, None]:
        observation = ProcessingObservation()
        started = perf_counter()
        try:
            yield observation
        except BaseException as error:
            observation.outcome = (
                MetricOutcome.ERROR
                if isinstance(error, Exception)
                else MetricOutcome.INTERRUPTED
            )
            raise
        finally:
            if not (
                stage == ProcessingStage.PIPELINE
                and observation.outcome == MetricOutcome.INTERRUPTED
            ):
                self.record(
                    stage, observation.outcome, max(0.0, perf_counter() - started)
                )

    def snapshot(self, day: date) -> ProcessingMetricsResponse:
        raw = self.repository.read(day)
        stages = {}
        for stage in ProcessingStage:

            def value(
                outcome: MetricOutcome,
                field: str,
                current_stage: ProcessingStage = stage,
            ) -> int:
                return int(raw.get(f"{current_stage.value}:{outcome.value}:{field}", 0))

            counts = {
                outcome.value: value(outcome, "count") for outcome in MetricOutcome
            }
            completed = (
                MetricOutcome.SUCCESS,
                MetricOutcome.ERROR,
                MetricOutcome.INTERRUPTED,
            )
            denominator = sum(counts[o.value] for o in completed)

            def mean(outcomes: tuple[MetricOutcome, ...]) -> float | None:
                samples = sum(value(o, "duration_count") for o in outcomes)
                return (
                    sum(value(o, "duration_us") for o in outcomes) / samples / 1_000_000
                    if samples
                    else None
                )

            stages[stage] = StageMetrics(
                attempts=sum(counts.values()),
                **counts,
                error_rate=(counts["error"] + counts["interrupted"]) / denominator
                if denominator
                else None,
                duration_samples=sum(value(o, "duration_count") for o in completed),
                mean_seconds=mean(completed),
                mean_success_seconds=mean((MetricOutcome.SUCCESS,)),
                mean_error_seconds=mean(
                    (MetricOutcome.ERROR, MetricOutcome.INTERRUPTED)
                ),
            )
        return ProcessingMetricsResponse(
            day=day, retention_days=self.repository.retention_days, stages=stages
        )


processing_metrics = ProcessingMetricsService(
    ProcessingMetricsRepository(
        Redis.from_url(
            setting.redis_url,
            decode_responses=True,
            socket_connect_timeout=metrics_settings.redis_timeout_seconds,
            socket_timeout=metrics_settings.redis_timeout_seconds,
            retry=Retry(NoBackoff(), 0),
        ),
        retention_days=metrics_settings.retention_days,
    )
)
