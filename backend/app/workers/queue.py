import logging
from uuid import UUID, uuid4

from redis import Redis
from redis.exceptions import RedisError
from rq import Callback, Queue, Retry

from backend.app.core.config import setting
from backend.app.core.logging import (
    get_correlation_id,
    log_context,
    normalize_correlation_id,
)


logger = logging.getLogger(__name__)

queue_connection = Redis.from_url(
    setting.redis_url,
    decode_responses=False,
)

receipt_queue = Queue(
    "receipts",
    connection=queue_connection,
    default_timeout=300,
)


def enqueue_receipt(
    receipt_id: UUID,
    processing_version: int = 1,
) -> str:
    intervals = list(setting.receipt_retry_intervals_seconds)

    retry = (
        Retry(max=len(intervals), interval=intervals)
        if intervals
        else None
    )

    correlation_id = normalize_correlation_id(get_correlation_id())

    job_id = str(uuid4())

    with log_context(
        correlation_id=correlation_id,
        job_id=job_id,
        receipt_id=str(receipt_id),
        processing_version=processing_version,
    ):
        logger.info("Receipt enqueue requested")

        try:
            job = receipt_queue.enqueue(
                "backend.app.workers.jobs.process_receipt",
                args=(str(receipt_id), processing_version),
                job_id=job_id,
                meta={
                    "correlation_id": correlation_id,
                },
                retry=retry,
                on_failure=Callback(
                    "backend.app.workers.retry_policy."
                    "receipt_failure_callback"
                ),
            )
        except RedisError:
            logger.exception("Could not confirm receipt enqueue")
            raise

        logger.info(
            "Receipt enqueued max_retries=%s retry_intervals=%s",
            len(intervals),
            intervals,
        )

    return job.id
