import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from signal import SIGINT, SIGTERM, signal
from types import FrameType

from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.logging import configure_logging, log_context
from backend.app.db.session import SessionLocal
from backend.app.models.enums import RUNNING_PROCESSING_STATUSES, ProcessingStatus
from backend.app.models.receipt import Receipt
from backend.app.services.receipt_processing_service import record_processing_failure
from backend.app.workers.queue import (
    dispatch_connection,
    enqueue_receipt,
    receipt_job_id,
)

logger = logging.getLogger(__name__)
QUEUE_CHECK_INTERVAL = timedelta(seconds=30)
DISPATCH_RETRY_DELAY = timedelta(seconds=5)
IDLE_WAIT_SECONDS = 1
DATABASE_RETRY_WAIT_SECONDS = 5


def _check_queued_receipt(receipt: Receipt, now: datetime) -> None:
    job_id = receipt_job_id(receipt.receipt_id, receipt.processing_version)
    try:
        job = Job.fetch(job_id, connection=dispatch_connection)
        status = job.get_status()
    except NoSuchJobError:
        receipt.processing_status = ProcessingStatus.PENDING_DISPATCH
        receipt.ocr_due_at = now
        return

    if status in {
        JobStatus.FAILED,
        JobStatus.STOPPED,
        JobStatus.CANCELED,
        JobStatus.FINISHED,
    }:
        record_processing_failure(
            receipt,
            RuntimeError("Queue job ended without a saved result"),
            retryable=True,
        )
        return

    receipt.ocr_due_at = now + QUEUE_CHECK_INTERVAL


def advance_due_receipt() -> bool:
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        receipt = session.scalar(
            select(Receipt)
            .where(Receipt.ocr_due_at <= now)
            .order_by(Receipt.ocr_due_at, Receipt.receipt_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if receipt is None:
            return False

        status = receipt.processing_status
        if status in RUNNING_PROCESSING_STATUSES:
            record_processing_failure(
                receipt, TimeoutError("Processing lease expired"), retryable=True
            )
            return True

        with log_context(
            correlation_id=receipt.ocr_correlation_id,
            receipt_id=str(receipt.receipt_id),
            processing_version=receipt.processing_version,
        ):
            try:
                if status == ProcessingStatus.QUEUED:
                    _check_queued_receipt(receipt, now)
                elif status in {
                    ProcessingStatus.PENDING_DISPATCH,
                    ProcessingStatus.RETRY_SCHEDULED,
                }:
                    enqueue_receipt(
                        receipt.receipt_id,
                        receipt.processing_version,
                        receipt.ocr_correlation_id,
                    )
                    receipt.processing_status = ProcessingStatus.QUEUED
                    receipt.ocr_due_at = now + QUEUE_CHECK_INTERVAL
                else:
                    receipt.ocr_due_at = None
            except RedisError:
                logger.warning(
                    "Redis unavailable while dispatching receipt", exc_info=True
                )
                receipt.ocr_due_at = now + DISPATCH_RETRY_DELAY

        return True


async def _run_dispatcher() -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop.set)

    previous_sigterm = signal(SIGTERM, request_stop)
    previous_sigint = signal(SIGINT, request_stop)
    try:
        while not stop.is_set():
            try:
                if await asyncio.to_thread(advance_due_receipt):
                    continue
                delay = IDLE_WAIT_SECONDS
            except SQLAlchemyError:
                logger.exception("Could not advance receipt processing")
                delay = DATABASE_RETRY_WAIT_SECONDS

            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
    finally:
        signal(SIGTERM, previous_sigterm)
        signal(SIGINT, previous_sigint)


def main() -> None:
    configure_logging()
    asyncio.run(_run_dispatcher())


if __name__ == "__main__":
    main()
