import logging
from uuid import UUID

from redis import Redis
from rq import Queue, Retry

from backend.app.core.config import setting

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


def enqueue_receipt(receipt_id: UUID, processing_version: int = 1) -> str:
    intervals = list(setting.receipt_retry_intervals_seconds)

    retry = Retry(max=len(intervals), interval=intervals) if intervals else None

    job = receipt_queue.enqueue(
        "backend.app.workers.jobs.process_receipt",
        args=(str(receipt_id), processing_version),
        retry=retry,
        on_failure=("backend.app.workers.retry_policy.receipt_failure_callback"),
    )

    logger.info(
        "Receipt job enqueued "
        "receipt_id=%s processing_version=%s job_id=%s "
        "max_retries=%s retry_intervals=%s",
        receipt_id,
        processing_version,
        job.id,
        len(intervals),
        intervals,
    )

    return job.id
