import logging
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError
from rq import Callback, Queue
from rq.exceptions import DuplicateJobError

from backend.app.core.config import setting
from backend.app.core.logging import log_context, normalize_correlation_id
from backend.app.services.receipt_processing_service import PROCESSING_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

queue_connection = Redis.from_url(setting.redis_url, decode_responses=False)
dispatch_connection = Redis.from_url(
    setting.redis_url,
    decode_responses=False,
    socket_connect_timeout=2,
    socket_timeout=2,
)
receipt_queue = Queue(
    "receipts", connection=queue_connection, default_timeout=PROCESSING_TIMEOUT_SECONDS
)
dispatch_queue = Queue(
    receipt_queue.name,
    connection=dispatch_connection,
    default_timeout=PROCESSING_TIMEOUT_SECONDS,
)


def receipt_job_id(receipt_id: UUID, processing_version: int) -> str:
    return f"receipt-{receipt_id}-{processing_version}"


def enqueue_receipt(
    receipt_id: UUID,
    processing_version: int,
    correlation_id: str | None,
) -> str:
    job_id = receipt_job_id(receipt_id, processing_version)
    correlation_id = normalize_correlation_id(correlation_id)
    with log_context(
        correlation_id=correlation_id,
        job_id=job_id,
        receipt_id=str(receipt_id),
        processing_version=processing_version,
    ):
        logger.info("Receipt enqueue requested")
        try:
            dispatch_queue.enqueue(
                "backend.app.workers.jobs.process_receipt",
                args=(str(receipt_id), processing_version),
                job_id=job_id,
                unique=True,
                meta={"correlation_id": correlation_id},
                on_failure=Callback(
                    "backend.app.workers.retry_policy.receipt_failure_callback",
                ),
            )
        except DuplicateJobError:
            logger.info("Receipt already enqueued")
        except RedisError:
            logger.exception("Receipt enqueue could not be confirmed")
            raise
        else:
            logger.info("Receipt enqueued")
    return job_id
