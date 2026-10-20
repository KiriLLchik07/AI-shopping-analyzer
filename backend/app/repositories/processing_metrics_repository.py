from datetime import UTC, date, datetime, time, timedelta

from redis import Redis

from backend.app.schemas.processing_metrics import MetricOutcome, ProcessingStage


class ProcessingMetricsRepository:
    def __init__(self, client: Redis, retention_days: int) -> None:
        self.client = client
        self.retention_days = retention_days

    @staticmethod
    def key(day: date) -> str:
        return f"metrics:receipts:{day.isoformat()}"

    def record(
        self,
        day: date,
        stage: ProcessingStage,
        outcome: MetricOutcome,
        elapsed_seconds: float | None,
    ) -> None:
        prefix = f"{stage.value}:{outcome.value}"
        expires = datetime.combine(
            day + timedelta(days=self.retention_days), time.min, UTC
        )
        with self.client.pipeline(transaction=True) as pipeline:
            pipeline.hincrby(self.key(day), f"{prefix}:count", 1)
            if elapsed_seconds is not None:
                pipeline.hincrby(self.key(day), f"{prefix}:duration_count", 1)
                pipeline.hincrby(
                    self.key(day),
                    f"{prefix}:duration_us",
                    round(elapsed_seconds * 1_000_000),
                )
            pipeline.expireat(self.key(day), expires)
            pipeline.execute()

    def read(self, day: date) -> dict[str, str]:
        return self.client.hgetall(self.key(day))
