import logging
from uuid import UUID

from redis import Redis
from rq import Queue

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

def enqueue_receipt(receipt_id: UUID) -> str:
    job = receipt_queue.enqueue(
        "backend.app.workers.jobs.process_receipt",
        args=(str(receipt_id),),
    )

    logger.info(
        "Receipt job enqueued receipt_id=%s job_id=%s", receipt_id, job.id,
    )
